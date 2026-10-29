"""Registry on the real Supabase database. Opt-in: SYNAPSE_TEST_PG=1 (needs SUPABASE_DB_URL and the migrations).

Uses throwaway ids (test-<hex>) with no owner (user_id references auth.users) and deletes them afterwards.
"""
import os
import secrets

import pytest

from backend.schemas import Label, TaskCard, Thresholds

real_db = pytest.mark.skipif(os.environ.get("SYNAPSE_TEST_PG") != "1", reason="set SYNAPSE_TEST_PG=1 to run")


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


@real_db
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


@real_db
def test_builds_rows(pg_registry):
    registry, tag = pg_registry
    rid = f"{tag}-build"
    registry.record_run(rid, "t", "build", "running", task_name="T", budget_usd=1.0)
    registry.record_run(rid, "t", "build", "stopped_budget", "sid-x", task_name="T", spend_usd=0.5,
                        message="budget", version=3, deployed=False)
    assert registry.run_owner(rid) == (True, None) and rid in registry.run_owners()
    row = next(r for r in registry.list_runs() if r["run_id"] == rid)
    assert (row["status"], row["specialist_id"]) == ("failed", "sid-x")


def test_stale_records_served_when_database_is_down(monkeypatch):
    """Not opt-in: fakes the database. Keys keep working from the last read while Postgres is unreachable."""
    from backend.schemas import Versions
    from backend.versions import registry
    monkeypatch.setattr(registry.pg, "enabled", lambda: True)
    v = Versions(specialist_id="cached-x", display_name="X", monogram="XX", color="#000", task_id="t", api_route="/r")
    calls = {"n": 0}

    def flaky(sid):
        calls["n"] += 1
        if calls["n"] > 1:
            raise ConnectionError("no route to host")
        return v
    monkeypatch.setattr(registry, "_pg_load", flaky)
    monkeypatch.setattr(registry, "CACHE_S", 0.0)
    registry._invalidate()
    assert registry.load("cached-x").specialist_id == "cached-x"          # fresh read
    assert registry.load("cached-x").specialist_id == "cached-x"          # database down: stale copy
    registry._invalidate()
    import pytest as _p
    with _p.raises(ConnectionError):                                       # nothing cached: the error surfaces
        registry.load("cached-x")
