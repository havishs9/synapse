"""Build queue and workers (TEAM_PLAN §2.3). Cancel and the event hook run offline on the tiny fixture; the queue
itself needs Postgres and is opt-in (SYNAPSE_TEST_PG=1, test rows are deleted afterwards)."""
import json
import os
import secrets

import pytest

from backend.schemas import Label, TaskCard, Thresholds
from backend.tests.test_integration import WORDS, fixture_env  # noqa: F401  (fixture)

real_db = pytest.mark.skipif(os.environ.get("SYNAPSE_TEST_PG") != "1", reason="set SYNAPSE_TEST_PG=1 to run")


def fixture_card(name="Fixture Categorizer"):
    return TaskCard(task_id="fixture", task_name=name, description="Sort purchase records.", input_type="text",
                    output_type="multiclass", labels=[Label(name=l) for l in WORDS],
                    thresholds=Thresholds(primary_min=0.5), monthly_volume=1000, dataset_key="fixture",
                    latency_budget_ms=5000)


def small_options():
    from backend.orchestrator import Options
    return Options(families=["J", "A"], limit_per_family=2, baseline_n=20, max_eval_llm=10, repair=False,
                   cascade=False, seeds=False)


def test_cancel_stops_after_the_round_and_listeners_see_every_event(fixture_env):
    from backend.orchestrator import Orchestrator
    orch = Orchestrator(fixture_card(), run_id="cancel-run", options=small_options())
    seen = []

    def listener(seq, e):
        seen.append((seq, e.kind))
        if e.kind == "round":
            orch.cancelled.set()                # user presses Cancel while round 1 runs
    orch.listeners.append(listener)
    orch.run()
    assert orch.state.status == "cancelled" and "Cancelled" in orch.state.message
    assert not orch.result.get("deployed")
    lines = [json.loads(l) for l in (orch.dir / "events.jsonl").open()]
    assert [s for s, _ in seen] == list(range(1, len(lines) + 1))       # every event, in file order
    assert lines[-1]["kind"] == "done" and lines[-1]["data"]["status"] == "cancelled"
    assert sum(1 for l in lines if l["kind"] == "round") == 1          # stopped before round 2
    state = json.loads((orch.dir / "run_state.json").read_text())
    assert state["status"] == "cancelled" and state["round"] == 1 and state["n_rounds"] >= 1


def test_job_command_masks_secrets_and_uses_pricing(monkeypatch):
    from backend.builds import dispatcher
    monkeypatch.setenv("NEBIUS_API_KEY", "super-secret-value")
    monkeypatch.setenv("NEBIUS_PROJECT_ID", "project-abc")
    cmd = dispatcher.job_command("20261029-000000-procurement-ab12")
    assert "NEBIUS_API_KEY=super-secret-value" in cmd and "SYNAPSE_RUN_ID=20261029-000000-procurement-ab12" in cmd
    shown = dispatcher.describe_job_command("20261029-000000-procurement-ab12")
    assert "super-secret-value" not in shown and "NEBIUS_API_KEY=***" in shown
    monkeypatch.setenv("WORKER_IMAGE", "cr.eu-west2.nebius.cloud/reg/synapse:main")
    monkeypatch.setenv("NEBIUS_REGISTRY", "cr.eu-west2.nebius.cloud/reg")
    monkeypatch.setenv("NEBIUS_REGISTRY_TOKEN", "registry-token-value")
    cmd = dispatcher.job_command("r1")
    assert cmd[cmd.index("--registry-password") + 1] == "registry-token-value"
    assert "registry-token-value" not in dispatcher.describe_job_command("r1")
    monkeypatch.setenv("WORKER_IMAGE", "python:3.12-slim")              # public image: no registry login
    assert "--registry-password" not in dispatcher.job_command("r1")
    cmd = dispatcher.job_command("20261029-000000-procurement-ab12")
    spec = dispatcher.worker_spec()
    assert cmd[cmd.index("--preset") + 1] == spec["preset"] and cmd[cmd.index("--parent-id") + 1] == "project-abc"
    assert cmd[cmd.index("--disk-size") + 1] == f"{spec['disk_gib']}Gi" and spec["hourly_usd"] > 0


def test_worker_budget_stops_job_launches(monkeypatch):
    from backend.builds import dispatcher
    finished, launched = [], []
    monkeypatch.setenv("TRAINING_BACKEND", "jobs")
    monkeypatch.setenv("WORKER_TOTAL_BUDGET_USD", "1.0")
    monkeypatch.setattr(dispatcher.queue, "worker_hours", lambda prefix="job:": 100.0)
    monkeypatch.setattr(dispatcher.queue, "finish", lambda run_id, status, msg="", **kw: finished.append((status, msg)))
    monkeypatch.setattr(dispatcher, "launch_job", lambda run_id: launched.append(run_id) or "job-1")
    dispatcher._launch({"run_id": "r1"})
    assert not launched and finished[0][0] == "failed" and "budget" in finished[0][1]


# ---- Postgres ------------------------------------------------------------------------------
@pytest.fixture
def pg_queue(tmp_env, monkeypatch):
    from backend.builds import queue
    from backend.storage import db
    monkeypatch.setenv("REGISTRY_BACKEND", "postgres")
    tag = f"test-{secrets.token_hex(4)}"
    yield queue, tag
    with db.conn() as c:
        c.execute("delete from builds where run_id like %s", (tag + "%",))
        c.execute("delete from specialists where specialist_id like %s", (tag + "%",))


def _card_json(tag):
    return fixture_card(tag).model_dump(mode="json")


@real_db
def test_queue_caps_cancel_retry_and_stale(pg_queue, monkeypatch):
    queue, tag = pg_queue
    monkeypatch.setenv("MAX_CONCURRENT_BUILDS", "1")
    a = queue.enqueue(f"{tag}-a", _card_json(tag), {"profile": "full"}, None, 1.0)
    queue.enqueue(f"{tag}-b", _card_json(tag), {"profile": "full"}, None, 1.0)
    assert a["status"] == "queued" and a["task_name"] == tag
    got = queue.claim("local:t", run_id_like=tag + "%")
    assert got["run_id"] == f"{tag}-a" and got["status"] == "running"
    assert queue.claim("local:t", run_id_like=tag + "%") is None          # cap of 1 running build
    assert queue.heartbeat(f"{tag}-a", stage="train", round=1, n_rounds=3, spend_usd=0.01) is False
    assert queue.request_cancel(f"{tag}-b")["status"] == "cancelled"       # queued: cancelled at once
    queue.request_cancel(f"{tag}-a")
    assert queue.heartbeat(f"{tag}-a", stage="train") is True              # running: the worker is told
    queue.append_events(f"{tag}-a", [(1, json.dumps({"kind": "narration", "message": "x"})),
                                     (2, json.dumps({"kind": "done", "data": {"status": "cancelled"}}))])
    assert [s for s, _ in queue.events_after(f"{tag}-a", 1)] == [2]
    queue.finish(f"{tag}-a", "cancelled", "Cancelled by the user")
    with pytest.raises(Exception) as e:                                    # anonymous callers share a daily cap
        monkeypatch.setenv("MAX_BUILDS_PER_USER_PER_DAY", "0")
        queue.enqueue(f"{tag}-x", _card_json(tag), {}, None, 1.0)
    assert e.value.status_code == 429
    monkeypatch.setenv("MAX_BUILDS_PER_USER_PER_DAY", "100")
    r = queue.retry(f"{tag}-b", f"{tag}-c")
    assert r["status"] == "queued" and r["run_id"] == f"{tag}-c"
    with pytest.raises(Exception):
        queue.retry(f"{tag}-c", f"{tag}-d")                                # still queued: 409
    got = queue.claim("local:t", run_id_like=tag + "%")
    from backend.storage import db
    with db.conn() as c:                                                   # worker went silent mid-build
        c.execute("update builds set stage = 'train', heartbeat_at = now() - interval '10 minutes' where run_id = %s",
                  (got["run_id"],))
    assert got["run_id"] in queue.reap_stale()
    assert queue.get(got["run_id"])["status"] == "failed"


@real_db
def test_worker_runs_a_queued_build_end_to_end(pg_queue, fixture_env, monkeypatch):
    from backend.builds import queue as q
    from backend.builds import worker
    queue, tag = pg_queue
    monkeypatch.setattr(worker, "HEARTBEAT_S", 0.5)
    import backend.orchestrator as orch_mod
    small = small_options()
    monkeypatch.setattr(orch_mod, "Options", lambda: small)          # a small search keeps the test fast
    run_id = f"{tag}-run"
    q.enqueue(run_id, _card_json(tag), {"profile": "full"}, None, 1.0)
    assert q.claim("local:t", run_id_like=tag + "%")["run_id"] == run_id
    assert worker.run_build(run_id) == "done"
    row = q.get(run_id)
    assert row["status"] == "done" and row["specialist_id"] == tag and row["version"] == 1
    events = q.events_after(run_id, 0, limit=10000)
    lines = (fixture_env / "runs" / run_id / "events.jsonl").read_text().splitlines()
    assert len(events) == len(lines) and events[-1][1]["kind"] == "done"


def test_quota_full_requeues_and_backs_off(monkeypatch):
    from backend.builds import dispatcher
    monkeypatch.setenv("TRAINING_BACKEND", "jobs")
    monkeypatch.setenv("WORKER_TOTAL_BUDGET_USD", "6")
    monkeypatch.setattr(dispatcher.queue, "worker_hours", lambda prefix="job:": 0.0)
    monkeypatch.setattr(dispatcher.queue, "reap_stale", lambda: [])
    claims, requeued = [{"run_id": "r1"}, {"run_id": "r2"}], []
    monkeypatch.setattr(dispatcher.queue, "claim", lambda kind, run_id_like="%": claims.pop(0) if claims else None)
    monkeypatch.setattr(dispatcher.queue, "requeue", lambda run_id, msg: requeued.append((run_id, msg)))

    class Out:
        returncode, stdout = 24, ""
        stderr = ("Error: rpc error: code = ResourceExhausted desc = Quota limit exceeded.\n"
                  "    compute.instance.count (limit 2, requested 3): Exceeded limit\n--env NEBIUS_API_KEY=secret\n")
    monkeypatch.setattr(dispatcher.subprocess, "run", lambda *a, **k: Out())
    monkeypatch.setattr(dispatcher, "_quota_until", 0.0)
    dispatcher.tick()
    assert requeued == [("r1", "Waiting for a free machine (Nebius compute quota is full)")]
    assert claims == [{"run_id": "r2"}]                    # stopped claiming after the quota error
    dispatcher.tick()                                      # within the back-off: nothing claimed
    assert claims == [{"run_id": "r2"}]
    assert "secret" not in dispatcher._error_summary(Out.stderr) and "compute.instance.count" in dispatcher._error_summary(Out.stderr)
