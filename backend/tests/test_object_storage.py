"""Object Storage: version bundles and run folders (TEAM_PLAN §2.2), with a local folder standing in for the bucket.
The last test uses the real bucket and is opt-in: SYNAPSE_TEST_S3=1."""
import json
import os
import secrets
import shutil

import pytest
from fastapi.testclient import TestClient

from backend.schemas import Label, TaskCard, Thresholds


def card(name):
    return TaskCard(task_id=name, task_name=name, description="d", input_type="text", output_type="multiclass",
                    labels=[Label(name="a"), Label(name="b")], thresholds=Thresholds(primary_min=0.5))


@pytest.fixture
def store(tmp_env, monkeypatch):
    bucket = tmp_env / "bucket"
    monkeypatch.setenv("OBJECT_STORAGE_BACKEND", f"local:{bucket}")
    return bucket


def _bundle(tmp_env, model=b"model-bytes"):
    b = tmp_env / "bundle-src"
    shutil.rmtree(b, ignore_errors=True)
    b.mkdir()
    (b / "bundle.json").write_text(json.dumps({"input_type": "text", "family": "A"}))
    (b / "model.joblib").write_bytes(model)
    return b


def test_version_upload_and_verified_download(store, tmp_env):
    from backend.storage import objects
    from backend.versions import registry
    v = registry.get_or_create(card("Stored Spec"), user_id="u1")
    rec = registry.add_version(v, "run-1", _bundle(tmp_env), {"primary": 0.9}, True, "first", "A-01")
    prefix = "users/u1/specialists/stored-spec/v1"
    assert rec.artifact_uri == objects.uri(prefix) and set(rec.artifact_files) == {"bundle.json", "model.joblib"}
    assert (store / prefix / "model.joblib").read_bytes() == b"model-bytes"
    local = registry.bundle_dir("stored-spec", 1)
    shutil.rmtree(local)                                    # a server that doesn't have the bundle
    assert registry.bundle_meta("stored-spec", 1)["family"] == "A"
    assert sorted(p.name for p in local.iterdir()) == ["bundle.json"]      # metadata fetches only bundle.json
    assert registry.ensure_bundle("stored-spec", 1) == local and (local / "model.joblib").read_bytes() == b"model-bytes"


def test_bundle_with_subfolder_downloads(store, tmp_env):
    """Rung G bundles keep the model in model/: the download must create the subfolder."""
    from backend.versions import registry
    v = registry.get_or_create(card("Nested Spec"), user_id="u1")
    src = _bundle(tmp_env)
    (src / "model").mkdir()
    (src / "model" / "weights.bin").write_bytes(b"w")
    registry.add_version(v, "run-1", src, {"primary": 0.9}, True, "first", "G-01")
    local = registry.bundle_dir("nested-spec", 1)
    shutil.rmtree(local)
    assert (registry.ensure_bundle("nested-spec", 1) / "model" / "weights.bin").read_bytes() == b"w"


def test_tampered_bundle_is_not_loaded(store, tmp_env):
    from backend.serving.server import create_app
    from backend.storage.objects import StorageError
    from backend.versions import registry
    v = registry.get_or_create(card("Stored Spec"))
    registry.add_version(v, "run-1", _bundle(tmp_env), {"primary": 0.9}, True, "first", "A-01")
    key = registry.create_key(registry.load("stored-spec"))
    shutil.rmtree(registry.bundle_dir("stored-spec", 1))
    (store / "users/public/specialists/stored-spec/v1/model.joblib").write_bytes(b"evil")      # bucket tampered
    with pytest.raises(StorageError, match="hash"):
        registry.ensure_bundle("stored-spec", 1)
    assert not (registry.bundle_dir("stored-spec", 1) / "model.joblib").exists()
    r = TestClient(create_app()).post("/v1/specialists/stored-spec/predict", json={"input": "x"},
                                      headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 503 and "hash" in r.json()["detail"]


def test_no_hashes_means_local_only(tmp_env):
    from backend.storage.objects import StorageError
    from backend.versions import registry
    v = registry.get_or_create(card("Old Spec"))
    rec = registry.add_version(v, "run-1", _bundle(tmp_env), {}, True, "", "A-01")
    v = registry.load("old-spec")
    v.versions[0].artifact_files = None                      # recorded before hashes existed
    registry.save(v)
    assert registry.ensure_bundle("old-spec", rec.version).exists()
    shutil.rmtree(registry.bundle_dir("old-spec", rec.version))
    with pytest.raises(StorageError):
        registry.ensure_bundle("old-spec", rec.version)


def test_run_upload_skips_candidate_models_and_is_fetched(store, tmp_env):
    from backend import main
    from backend.storage import objects
    run = tmp_env / "runs" / "r-up"
    (run / "candidates" / "A-01" / "r1").mkdir(parents=True)
    (run / "candidates" / "A-01" / "r1" / "model.joblib").write_bytes(b"x" * 1000)
    (run / "candidates" / "A-01" / "r1" / "metrics.json").write_text("{}")
    (run / "bundle").mkdir()
    (run / "bundle" / "model.joblib").write_bytes(b"y")
    (run / "sealed").mkdir()
    (run / "sealed" / "test.jsonl").write_text("{}\n")
    (run / "run_state.json").write_text(json.dumps({"run_id": "r-up", "task_id": "t", "stage": "end", "budget_usd": 1,
                                                    "started": 1, "updated": 2, "status": "done"}))
    assert objects.upload_run(run, None) == 3
    keys = objects.list_keys("users/public/runs/r-up")
    assert sorted(k.split("r-up/")[1] for k in keys) == ["candidates/A-01/r1/metrics.json", "run_state.json",
                                                         "sealed/test.jsonl"]
    shutil.rmtree(run)                                       # this server never ran it
    c = TestClient(main.app)
    assert c.get("/api/runs/r-up/state").json()["status"] == "done"
    assert (tmp_env / "runs" / "r-up" / "sealed" / "test.jsonl").exists()
    assert c.get("/api/runs/never-existed/state").status_code == 404


def test_predictor_cache_is_bounded(store, tmp_env, monkeypatch):
    from backend.serving import server
    from backend.versions import registry
    monkeypatch.setenv("SPECIALIST_CACHE_SIZE", "2")
    monkeypatch.setattr(server, "Predictor", lambda d, llm=None: object())
    monkeypatch.setattr(server, "_get_llm", lambda: None)
    server._cache.clear()
    for name in ("One", "Two", "Three"):
        v = registry.get_or_create(card(name))
        registry.add_version(v, "r", _bundle(tmp_env), {}, True, "", "A-01")
    server.predictor("one", 1), server.predictor("two", 1), server.predictor("one", 1), server.predictor("three", 1)
    assert list(server._cache) == [("one", 1), ("three", 1)]     # "two" was least recently used
    server._cache.clear()


@pytest.mark.skipif(os.environ.get("SYNAPSE_TEST_S3") != "1", reason="set SYNAPSE_TEST_S3=1 to use the real bucket")
def test_real_bucket_round_trip(tmp_path, monkeypatch):
    from backend.storage import objects
    monkeypatch.setenv("OBJECT_STORAGE_BACKEND", "s3")
    assert objects.mode() == "s3"
    prefix = f"_test/{secrets.token_hex(4)}"
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_text("hello")
    (src / "sub" / "b.bin").write_bytes(os.urandom(9 * 1024 * 1024))       # multipart upload
    try:
        assert objects.upload_dir(src, prefix) == 2
        objects.download_dir(prefix, tmp_path / "dst")
        assert objects.file_hashes(tmp_path / "dst") == objects.file_hashes(src)
    finally:
        assert objects.delete_prefix(prefix) == 2
    assert objects.list_keys(prefix) == []
