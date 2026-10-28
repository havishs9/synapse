"""Full pipeline on a tiny fixture (a few hundred rows) with LLM calls mocked; must finish in under 2 minutes."""
import json
import random
import time

import pytest

from backend import config
from backend.agents import data_agent
from backend.schemas import Label, TaskCard, Thresholds

WORDS = {"IT": ["laptop", "software", "server", "network", "license"],
         "Medical": ["pharmaceutical", "surgical", "vaccine", "clinic", "x-ray"],
         "Facilities & Construction": ["roof", "janitorial", "hvac", "paving", "plumbing"]}


def fixture_rows(n=360, seed=0):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        label = list(WORDS)[i % 3]
        words = rng.sample(WORDS[label], 2) + rng.sample([w for l in WORDS for w in WORDS[l]], 1)
        if rng.random() < 0.15:                      # label noise keeps the task below a perfect score
            label = rng.choice(list(WORDS))
        rows.append({"id": f"f{i}", "text": f"PURCHASE OF {' '.join(words).upper()} ITEM {i}", "label": label})
    return rows, {"raw_rows": n}


@pytest.fixture
def fixture_env(tmp_env, monkeypatch):
    monkeypatch.setenv("SYNAPSE_FAKE_LLM", "1")
    monkeypatch.setenv("MAX_REPAIR_ROUNDS", "1")
    monkeypatch.setitem(data_agent.LOADERS, "fixture", fixture_rows)
    real = config.datasets()
    monkeypatch.setattr(config, "datasets", lambda: {**real, "fixture": {
        "source": "test fixture", "license": "test", "license_ok": True}})
    return tmp_env


def test_full_pipeline_on_fixture(fixture_env):
    from backend.orchestrator import Options, Orchestrator
    card = TaskCard(task_id="fixture", task_name="Fixture Categorizer", description="Sort purchase records.",
                    input_type="text", output_type="multiclass", labels=[Label(name=l) for l in WORDS],
                    thresholds=Thresholds(primary_min=0.99), needs_reason=True, monthly_volume=1000,
                    dataset_key="fixture", latency_budget_ms=5000)
    t0 = time.time()
    orch = Orchestrator(card, run_id="fixture-run", options=Options(families=["J", "A", "E", "K"], limit_per_family=2,
                                                                    baseline_n=30, max_eval_llm=20))
    result = orch.run()
    elapsed = time.time() - t0
    assert orch.state.status == "done", (orch.dir / "error.log").read_text() if (orch.dir / "error.log").exists() else orch.state.message
    assert elapsed < 120
    d = orch.dir
    for name in ("task_card.json", "dataset_manifest.json", "dataset_stats.json", "candidate_plan.json", "runs.json",
                 "eval_report.json", "error_patterns.json", "report_card.json", "report_card.md", "events.jsonl"):
        assert (d / name).exists(), name
    plan = json.loads((d / "candidate_plan.json").read_text())
    assert plan["planner_source"] == "deterministic_fallback"          # fake planner output is unusable
    rep = json.loads((d / "eval_report.json").read_text())
    assert rep["final"]["n"] > 0 and rep["baseline"]["n"] > 0 and rep["teacher_agreement"]["n"] > 0
    assert rep["repair_rounds"], "target 0.99 is unreachable, so a repair round should have run"
    assert result["specialist_id"] == "fixture-categorizer"
    assert result["deployed"] is False                                   # can't pass a 0.99 target
    events = [json.loads(l) for l in (d / "events.jsonl").open()]
    assert events[-1]["kind"] == "done"
