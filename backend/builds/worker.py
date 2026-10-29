"""Run one queued build: the same code in an API-server thread (TRAINING_BACKEND=local) and in a Nebius AI Job
(TRAINING_BACKEND=jobs, `python -m backend.builds.worker <run_id>`).

While the build runs it mirrors every event into build_events (batched, in order), heartbeats progress into the
builds row every HEARTBEAT_S, and turns a cancel request into Orchestrator.cancelled (honoured after the current
search round or stage). The orchestrator uploads the run folder to Object Storage at the end.
"""
from __future__ import annotations

import argparse
import queue as _q
import sys
import threading
import traceback

from backend.builds import queue
from backend.schemas import TaskCard

HEARTBEAT_S = 15.0
FLUSH_S = 1.0


class _EventMirror:
    """Copies orchestrator events into build_events from a background thread, keeping their order."""

    def __init__(self, run_id: str):
        self.run_id, self.q, self.stop = run_id, _q.Queue(), threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True, name=f"events-{run_id}")
        self.thread.start()

    def __call__(self, seq: int, event) -> None:
        self.q.put((seq, event.model_dump_json()))

    def _drain(self) -> None:
        batch = []
        while True:
            try:
                batch.append(self.q.get_nowait())
            except _q.Empty:
                break
        for attempt in range(5):
            try:
                queue.append_events(self.run_id, batch)
                return
            except Exception as exc:
                print(f"[worker] couldn't write {len(batch)} events (attempt {attempt + 1}): {exc}", flush=True)
                self.stop.wait(2 ** attempt)

    def _loop(self) -> None:
        while not self.stop.wait(FLUSH_S):
            self._drain()
        self._drain()

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=60)


def _heartbeats(orch, stop: threading.Event) -> None:
    while not stop.wait(HEARTBEAT_S):
        s = orch.state
        try:
            if queue.heartbeat(orch.run_id, stage=s.stage, round=s.round, n_rounds=s.n_rounds,
                               spend_usd=round(s.spend_usd, 6), message=s.message or f"Running: {s.stage}"):
                orch.cancelled.set()
        except Exception as exc:       # a missed heartbeat is fine; several in a row mark the build failed
            print(f"[worker] heartbeat failed: {type(exc).__name__}: {exc}", flush=True)


def run_build(run_id: str) -> str:
    """Run a claimed build to the end; returns its final status."""
    from backend.orchestrator import PHASE1, Options, Orchestrator
    from backend.storage import datasets

    card_json, opts = queue.task_card(run_id)
    row = queue.get(run_id)
    card = TaskCard.model_validate(card_json)
    try:
        fetched = datasets.ensure(card.dataset_key)
        if fetched:
            print(f"[worker] downloaded {', '.join(fetched)}", flush=True)
    except Exception as exc:
        queue.finish(run_id, "failed", f"Couldn't fetch the dataset: {type(exc).__name__}: {exc}")
        return "failed"
    orch = Orchestrator(card, run_id=run_id, options=PHASE1 if opts.get("profile") == "phase1" else Options(),
                        user_id=row["user_id"])
    mirror = _EventMirror(run_id)
    orch.listeners.append(mirror)
    stop = threading.Event()
    hb = threading.Thread(target=_heartbeats, args=(orch, stop), daemon=True, name=f"heartbeat-{run_id}")
    hb.start()
    if row.get("cancel_requested"):
        orch.cancelled.set()
    try:
        orch.run()
    except Exception as exc:          # Orchestrator.run catches build errors; this is a bug in the worker itself
        traceback.print_exc()
        orch.state.status, orch.state.message = "failed", f"{type(exc).__name__}: {exc}"
    finally:
        stop.set()
        mirror.close()
    status = {"stopped_budget": "failed"}.get(orch.state.status, orch.state.status)
    queue.finish(run_id, status, orch.state.message, spend_usd=round(orch.state.spend_usd, 6),
                 specialist_id=orch.result.get("specialist_id"), version=orch.result.get("version"),
                 deployed=orch.result.get("deployed"), stage=orch.state.stage)
    return status


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_id")
    args = ap.parse_args(argv)
    status = run_build(args.run_id)
    print(f"[worker] {args.run_id} finished: {status}", flush=True)
    return 0 if status in ("done", "cancelled") else 1


if __name__ == "__main__":
    sys.exit(main())
