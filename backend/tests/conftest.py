import pytest


@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    """Point data, runs and artifacts at a temp dir; set a fake pepper/admin token."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("API_KEY_PEPPER", "test-pepper")
    monkeypatch.setenv("SPECIALIST_ADMIN_TOKEN", "test-admin")
    (tmp_path / "runs").mkdir()
    return tmp_path
