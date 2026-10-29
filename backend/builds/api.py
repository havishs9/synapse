"""Builds list for the sidebar (contract: docs/TEAM_PLAN.md §1).

Day-1 stub: reads each run folder's run_state.json, task_card.json and events.jsonl. The build queue
(TEAM_PLAN §2.3) replaces the source with the `builds` table; the response shape stays the same.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend import config

router = APIRouter(prefix="/api/builds")

STALE_S = 20 * 60          # a running build with no new event for this long is reported as failed
_STATUS = {"running": "running", "done": "done", "failed": "failed", "stopped_budget": "failed"}
_cache: dict[Path, tuple[tuple, dict]] = {}


def _mtime(p: Path) -> float:
    return p.stat().st_mtime if p.exists() else 0.0


def _progress(events: Path) -> dict:
    """Latest search round and the run's outcome, from the event stream."""
    out: dict = {"round": None, "n_rounds": None, "specialist_id": None, "version": None, "deployed": None}
    if not events.exists():
        return out
    for line in events.open():
        if '"kind": "round"' not in line and '"kind":"round"' not in line \
                and '"kind": "done"' not in line and '"kind":"done"' not in line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        d = e.get("data") or {}
        if e.get("kind") == "round":
            out["round"], out["n_rounds"] = d.get("round"), d.get("n_rounds") or out["n_rounds"]
        elif e.get("kind") == "done":
            out["specialist_id"], out["version"], out["deployed"] = d.get("specialist_id"), d.get("version"), d.get("deployed")
    return out


def build_view(run: Path) -> dict | None:
    state_p, card_p, events_p = run / "run_state.json", run / "task_card.json", run / "events.jsonl"
    if not state_p.exists():
        return None
    key = (_mtime(state_p), _mtime(events_p))
    hit = _cache.get(run)
    if hit and hit[0] == key:
        view = dict(hit[1])
    else:
        try:
            s = json.loads(state_p.read_text())
            card = json.loads(card_p.read_text()) if card_p.exists() else {}
        except json.JSONDecodeError:
            return None
        prog = _progress(events_p)
        if prog["n_rounds"] is None and s.get("status") == "done" and (run / "eval_report.json").exists():
            try:   # runs recorded before round events carried n_rounds
                prog["n_rounds"] = len(json.loads((run / "eval_report.json").read_text()).get("validation_rounds") or []) or None
            except json.JSONDecodeError:
                pass
        view = {"run_id": s.get("run_id", run.name), "task_id": s.get("task_id"),
                "task_name": card.get("task_name") or s.get("task_id"),
                "status": _STATUS.get(s.get("status"), "failed"), "stage": s.get("stage"),
                "round": prog["round"], "n_rounds": prog["n_rounds"],
                "spend_usd": round(float(s.get("spend_usd") or 0.0), 6), "budget_usd": s.get("budget_usd"),
                "created_at": s.get("started"), "updated_at": s.get("updated"),
                "message": s.get("message") or "", "specialist_id": prog["specialist_id"],
                "version": prog["version"], "deployed": prog["deployed"], "kind": s.get("kind", "build")}
        _cache[run] = (key, view)
        view = dict(view)
    if view["status"] == "running" and time.time() - (view["updated_at"] or 0) > STALE_S:
        view["status"] = "failed"
        view["message"] = f"No progress for over {STALE_S // 60} minutes; the build process stopped."
    return view


@router.get("")
def list_builds():
    """The caller's builds, newest first. Until logins land (TEAM_PLAN §2.1) that is every run in RUNS_DIR."""
    views = [v for d in config.runs_dir().iterdir() if d.is_dir() and (v := build_view(d))] \
        if config.runs_dir().exists() else []
    return sorted(views, key=lambda v: -(v["created_at"] or 0))


def _not_yet(run_id: str, action: str):
    d = (config.runs_dir() / run_id).resolve()
    if d.parent != config.runs_dir() or not build_view(d):
        raise HTTPException(404, "No such build.")
    raise HTTPException(501, f"{action} arrives with the build queue (TEAM_PLAN §2.3).")


@router.post("/{run_id}/cancel")
def cancel_build(run_id: str):
    _not_yet(run_id, "Cancel")


@router.post("/{run_id}/retry")
def retry_build(run_id: str):
    _not_yet(run_id, "Retry")
