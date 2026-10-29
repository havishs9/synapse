"""Builds list contract (docs/TEAM_PLAN.md §1), event-stream reconnects, CORS origins."""
import json
import time

from fastapi.testclient import TestClient

CONTRACT_KEYS = {"run_id", "task_id", "task_name", "status", "stage", "round", "n_rounds", "spend_usd", "budget_usd",
                 "created_at", "updated_at", "message", "specialist_id", "version"}


def _run(runs, run_id, status="done", started=1.0, updated=None, events=(), card=True):
    d = runs / run_id
    d.mkdir()
    (d / "run_state.json").write_text(json.dumps({
        "run_id": run_id, "task_id": "support_tickets", "stage": "end" if status == "done" else "train",
        "spend_usd": 0.31, "budget_usd": 1.0, "started": started, "updated": updated or started + 1,
        "status": status, "message": "Run complete" if status == "done" else "", "kind": "build"}))
    if card:
        (d / "task_card.json").write_text(json.dumps({"task_id": "support_tickets", "task_name": "Support Ticket Router"}))
    with (d / "events.jsonl").open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    return d


def _ev(kind, data, i=0):
    return {"ts": 100.0 + i, "agent": "Trainer", "stage": "train", "message": f"e{i}", "data_ref": None,
            "spend_usd": 0.0, "kind": kind, "data": data}


def _client():
    from backend import main
    return TestClient(main.app)


def test_builds_list_shape_and_order(tmp_env):
    runs = tmp_env / "runs"
    _run(runs, "old", started=10.0, events=[_ev("round", {"round": 1, "n_rounds": 3}, 0),
                                              _ev("round", {"round": 3, "n_rounds": 3}, 1),
                                              _ev("done", {"status": "done", "specialist_id": "support-ticket-router",
                                                           "version": 2, "deployed": False}, 2)])
    now = time.time()
    _run(runs, "new", status="running", started=now, updated=now, events=[_ev("round", {"round": 2, "n_rounds": 3})])
    out = _client().get("/api/builds").json()
    assert [b["run_id"] for b in out] == ["new", "old"]
    assert all(CONTRACT_KEYS <= set(b) for b in out)
    new, old = out
    assert (new["status"], new["round"], new["n_rounds"], new["specialist_id"]) == ("running", 2, 3, None)
    assert (old["status"], old["round"], old["specialist_id"], old["version"]) == ("done", 3, "support-ticket-router", 2)
    assert old["task_name"] == "Support Ticket Router" and old["spend_usd"] == 0.31
    assert old["deployed"] is False and new["deployed"] is None


def test_stale_and_budget_stopped_runs_report_failed(tmp_env):
    runs = tmp_env / "runs"
    _run(runs, "stale", status="running", started=1.0, updated=2.0)
    _run(runs, "budget", status="stopped_budget", started=3.0)
    out = {b["run_id"]: b for b in _client().get("/api/builds").json()}
    assert out["stale"]["status"] == "failed" and "No progress" in out["stale"]["message"]
    assert out["budget"]["status"] == "failed"


def test_cancel_retry_need_the_queue(tmp_env):
    _run(tmp_env / "runs", "r1")
    c = _client()
    for url in ("/api/builds/r1/cancel", "/api/builds/r1/retry", "/api/builds/nope/cancel"):
        assert c.post(url).status_code == 501          # no database: there is no queue to cancel or retry in


def test_events_stream_after_skips_but_still_ends(tmp_env):
    evs = [_ev("narration", {}, i) for i in range(4)] + [_ev("done", {"status": "done"}, 4)]
    _run(tmp_env / "runs", "r1", events=evs)
    c = _client()

    def stream(q):
        with c.stream("GET", f"/api/runs/r1/events{q}") as r:
            return [json.loads(l[5:]) for l in r.iter_lines() if l.startswith("data:")]
    assert [e["message"] for e in stream("")] == ["e0", "e1", "e2", "e3", "e4"]
    assert [e["message"] for e in stream("?after=3")] == ["e3", "e4"]
    assert stream("?after=10") == []          # done event skipped, but the stream still closes


def test_cors_origins(monkeypatch):
    from backend import config
    monkeypatch.setenv("CORS_ORIGINS", "https://synapse.vercel.app/, https://x.example ,")
    assert config.cors_origins() == ["http://localhost:5173", "http://127.0.0.1:5173", "https://synapse.vercel.app",
                                     "https://x.example"]
