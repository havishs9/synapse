"""The Data agent and the Trainer can't read the sealed test set; only the Evaluator can."""
import inspect
import json

import pytest

from backend import sealed
from backend.agents import data_agent, evaluator_agent, trainer_agent
from backend.sandbox import worker


def make_run(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    sealed.write_sealed(run, [{"id": "t1", "text": "secret", "label": "a"}])
    return run


def test_load_split_refuses_sealed_path(tmp_path):
    run = make_run(tmp_path)
    with pytest.raises(sealed.SealedAccessError):
        sealed.load_split(run / "sealed" / "test.jsonl")


def test_read_sealed_rejects_other_callers(tmp_path):
    run = make_run(tmp_path)
    with pytest.raises(sealed.SealedAccessError):
        sealed.read_sealed(run)                      # this test module is not the Evaluator


def test_evaluator_can_read(tmp_path):
    run = make_run(tmp_path)
    ns = {"__name__": "backend.agents.evaluator_agent", "read_sealed": sealed.read_sealed, "run": run}
    exec("rows = read_sealed(run)", ns)
    assert ns["rows"][0]["text"] == "secret"


def test_sealed_written_once_and_read_only(tmp_path):
    run = make_run(tmp_path)
    with pytest.raises(sealed.SealedAccessError):
        sealed.write_sealed(run, [])
    with pytest.raises(PermissionError):
        (run / "sealed" / "test.jsonl").open("w")


def test_trainer_worker_job_cannot_point_at_sealed(tmp_path):
    run = make_run(tmp_path)
    job = tmp_path / "job.json"
    job.write_text(json.dumps({"cand": "A-01", "family": "A", "params": {}, "seed": 0, "round": 1, "data_frac": 1.0,
                               "run_dir": str(run), "train_path": str(run / "sealed" / "test.jsonl"),
                               "val_path": str(run / "sealed" / "test.jsonl"), "out_dir": str(tmp_path / "o")}))
    with pytest.raises(sealed.SealedAccessError):
        worker.main(str(job))


def test_data_and_trainer_modules_never_call_read_sealed():
    for mod in (data_agent, trainer_agent, worker):
        assert "read_sealed" not in inspect.getsource(mod)
    assert "read_sealed" in inspect.getsource(evaluator_agent)


def test_data_agent_paths_exclude_sealed():
    fields = data_agent.DataPaths.__dataclass_fields__
    assert "test" not in fields and "sealed" not in fields
