"""Registry on the real Supabase database. Opt-in: SYNAPSE_TEST_PG=1 (needs SUPABASE_DB_URL and the migrations).

Uses throwaway ids (test-<hex>) with no owner (user_id references auth.users) and deletes them afterwards.
"""
import os
import secrets

import pytest

from backend.schemas import Label, TaskCard, Thresholds

pytestmark = pytest.mark.skipif(os.environ.get("SYNAPSE_TEST_PG") != "1", reason="set SYNAPSE_TEST_PG=1 to run")


@pytest.fixture
def pg_registry(tmp_env, monkeypatch):
    from backend.storage import db
    from backend.versions import registry
    monkeypatch.setenv("REGISTRY_BACKEND", "postgres")
    assert db.enabled(), "SUPABASE_DB_URL is empty"
    tag = f"test-{secrets.token_hex(4)}"
    yield registry, tag
    with db.conn() as c:
        c.execute("delete from specialists where specialist_id like %s", (tag + "%",))
        c.execute("delete from builds where run_id like %s", (tag + "%",))
    registry._invalidate()


def test_round_trip_keys_versions_rollback(pg_registry, tmp_path):
    registry, tag = pg_registry
    card = TaskCard(task_id="t", task_name=tag, description="d", input_type="text", output_type="multiclass",
                    labels=[Label(name="a"), Label(name="b")], thresholds=Thresholds(primary_min=0.5))
    v = registry.get_or_create(card)
    assert v.specialist_id == tag and registry.exists(tag)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "bundle.json").write_text("{}")
    r1 = registry.add_version(v, f"{tag}-run1", bundle, {"primary": 0.7}, True, "first", "A-01")
    r2 = registry.add_version(registry.load(tag), f"{tag}-run2", bundle, {"primary": 0.8}, True, "better", "A-02")
    key = registry.create_key(registry.load(tag))
    registry._invalidate()                                     # read back from the database, not the cache
    got = registry.load(tag)
    assert [r.version for r in got.versions] == [r1.version, r2.version] == [1, 2]
    assert registry.live(got).version == 2 and got.versions[0].sealed_metrics == {"primary": 0.7}
    assert registry.key_matches(got, key) and key not in got.model_dump_json()
    registry.rollback(got)
    registry._invalidate()
    got = registry.load(tag)
    assert registry.live(got).version == 1 and got.versions[1].gate_result == "rolled_back"
    new = registry.create_key(got)
    registry._invalidate()
    got = registry.load(tag)
    assert not registry.key_matches(got, key) and registry.key_matches(got, new)
    assert tag in [s.specialist_id for s in registry.list_specialists()]


def test_builds_rows(pg_registry):
    registry, tag = pg_registry
    rid = f"{tag}-build"
    registry.record_run(rid, "t", "build", "running", task_name="T", budget_usd=1.0)
    registry.record_run(rid, "t", "build", "stopped_budget", "sid-x", task_name="T", spend_usd=0.5,
                        message="budget", version=3, deployed=False)
    assert registry.run_owner(rid) == (True, None) and rid in registry.run_owners()
    row = next(r for r in registry.list_runs() if r["run_id"] == rid)
    assert (row["status"], row["specialist_id"]) == ("failed", "sid-x")
