"""Product routes: intake (questions → task card with plan changes), corrections, and the improve flow
(corrections → retrain → final exam on the same sealed test set → version gate → deploy or reject)."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from backend.routes import product
from backend.schemas import Label, TaskCard, Thresholds
from backend.tests.test_integration import WORDS, fixture_env  # noqa: F401  (fixture)


def test_parse_number():
    assert product.parse_number("about 2 million a month") == 2_000_000
    assert product.parse_number("500k") == 500_000
    assert product.parse_number("2,000,000") == 2_000_000
    assert product.parse_number("under 50 ms") == 50
    assert product.parse_number("$1.50") == 1.5
    assert product.parse_number("no idea") is None


def test_questions_at_most_seven():
    for task in ("procurement", "hdfs_logs"):
        qs = product.questions_for(product.base_card(task))
        assert 1 <= len(qs) <= 7
        assert all(q["options"] for q in qs)


def test_answers_change_the_plan(monkeypatch):
    monkeypatch.setenv("CREDIT_BUDGET_USD", "1")
    logs = product.base_card("hdfs_logs")
    card, changes = product.apply_answers(logs, {"error_preference": "precision_first", "deployment": "offline",
                                                  "needs_reason": False, "monthly_volume": 2_000_000,
                                                  "build_budget_usd": 3, "target": 0.8}, {})
    assert card.optimization_metric == "recall_at_fpr" and card.fpr_target == 0.001
    assert card.deployment == "offline" and card.needs_reason is False and card.monthly_volume == 2_000_000
    assert card.build_budget_usd == 1.0                                   # capped at CREDIT_BUDGET_USD
    assert card.thresholds.primary_min == 0.8
    text = " ".join(c["change"] for c in changes)
    assert "removed: prompted Nemotron (K)" in text and "caps one build at $1.00" in text
    assert "Super" not in text and "Qwen3" not in text           # never in a logs plan, so never "removed"
    assert card.plan_changes == [c["change"] for c in changes]

    card, _ = product.apply_answers(logs, {"error_preference": "balanced"}, {})
    assert card.optimization_metric == "pr_auc"                           # never plain accuracy on rare anomalies
    proc, changes = product.apply_answers(product.base_card("procurement"), {"error_preference": "recall_first"},
                                          {"labels": "Count toner as office supplies"})
    assert proc.thresholds.per_class_floor == 0.30
    _, changes = product.apply_answers(product.base_card("procurement"), {"needs_reason": False, "deployment": "offline"}, {})
    text = " ".join(c["change"] for c in changes)
    assert "Super, L) dropped" in text and "Qwen3 embeddings (B)" in text
    assert "toner" in proc.description and any(c["question"] == "labels" for c in changes)


def test_intake_without_the_model(tmp_env, monkeypatch):
    import backend.main as main
    monkeypatch.setattr(product, "_llm_intake", lambda text, samples: None)     # Nemotron unreachable
    c = TestClient(main.app)
    r = c.post("/api/intake/start", json={"text": "Flag anomalies in our server logs"}).json()
    assert r["task_id"] == "hdfs_logs" and r["source"] == "fallback" and len(r["questions"]) <= 7
    r = c.post("/api/intake/start", json={"text": "Classify my cat photos by breed"}).json()
    assert r["task_id"] is None and "vetted datasets" in r["message"]
    r = c.post("/api/intake/card", json={"task_id": "hdfs_logs", "answers": {"deployment": "offline"},
                                         "texts": {"monthly_volume": "roughly 3 million"}}).json()
    assert r["card"]["deployment"] == "offline" and r["card"]["monthly_volume"] == 3_000_000
    assert c.post("/api/intake/card", json={"task_id": "nope"}).status_code == 404


def _build_v1(target=0.5):
    from backend.orchestrator import Options, Orchestrator
    card = TaskCard(task_id="fixture", task_name="Fixture Categorizer", description="Sort purchase records.",
                    input_type="text", output_type="multiclass", labels=[Label(name=l) for l in WORDS],
                    thresholds=Thresholds(primary_min=target), needs_reason=True, monthly_volume=1000,
                    dataset_key="fixture", latency_budget_ms=5000)
    orch = Orchestrator(card, run_id="fixture-v1", options=Options(
        families=["J", "A"], limit_per_family=2, repair=False, cascade=False, seeds=False, baseline_n=20, max_eval_llm=20))
    result = orch.run()
    assert orch.state.status == "done" and result["deployed"], orch.state.message
    return orch, result["specialist_id"]


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_improve_deploys_or_rejects_through_the_gate(fixture_env):
    import backend.main as main
    from backend import config
    from backend.improve import Improver
    from backend.versions import registry
    orch, sid = _build_v1()
    sealed = orch.dir / "sealed" / "test.jsonl"
    sealed_before = _sha(sealed)
    c = TestClient(main.app)

    # corrections: validated against the specialist's labels, deduplicated, stored per user
    assert c.post(f"/api/specialists/{sid}/improve").status_code == 422           # nothing to train on yet
    bad = {"input": "PURCHASE OF LAPTOP", "predicted_label": "Medical", "corrected_label": "Toys"}
    assert c.post(f"/api/specialists/{sid}/corrections", json={"corrections": [bad]}).status_code == 422
    held = c.get(f"/api/specialists/{sid}/holdback").json()
    assert held["total"] > 0 and held["scored"] == held["total"]
    fixes = [{"input": f"PURCHASE OF LAPTOP SERVER NETWORK BATCH {i}", "predicted_label": "Medical", "corrected_label": "IT"}
             for i in range(5)]
    rows = c.post(f"/api/specialists/{sid}/corrections", json={"corrections": fixes + fixes[:2]}).json()["corrections"]
    assert len(rows) == 5

    # a passing improve: the live version's gate number is lowered so any working retrain beats it
    v = registry.load(sid)
    registry.live(v).sealed_metrics["primary"] = 0.01
    registry.save(v)
    imp = Improver(sid, rows)
    res = imp.run()
    assert imp.state.status == "done", (imp.dir / "error.log").read_text() if (imp.dir / "error.log").exists() else imp.state.message
    assert res["version"] == 2 and res["deployed"] is True
    assert registry.live(registry.load(sid)).version == 2
    assert _sha(sealed) == sealed_before                                       # the fixed benchmark is untouched
    train = [json.loads(l) for l in (imp.dir / "train.jsonl").open()]
    assert sum(r.get("correction", False) for r in train) == 5                 # corrections went to training only
    sealed_texts = {json.loads(l)["text"] for l in sealed.open()}
    assert not sealed_texts & {f["input"] for f in fixes}
    assert not (imp.dir / "sealed").exists()                                   # no new sealed set: v2 used v1's
    rep = json.loads((imp.dir / "improve_report.json").read_text())
    assert rep["base_run_id"] == "fixture-v1" and rep["final"]["n"] == sum(1 for _ in sealed.open())
    events = [json.loads(l) for l in (imp.dir / "events.jsonl").open()]
    assert events[-1]["kind"] == "done" and events[-1]["data"]["kind"] == "improve"
    assert (imp.dir / "report_card.md").exists()

    # a failing improve: the live version's number is out of reach, so v3 is rejected and v2 stays live
    v = registry.load(sid)
    registry.live(v).sealed_metrics["primary"] = 1.0
    registry.save(v)
    imp3 = Improver(sid, rows)
    res = imp3.run()
    assert json.loads((imp3.dir / "improve_report.json").read_text())["benchmark_run_id"] == "fixture-v1"
    assert res["version"] == 3 and res["deployed"] is False and "does not beat" in res["reason"]
    v = registry.load(sid)
    assert registry.live(v).version == 2
    assert next(r for r in v.versions if r.version == 3).gate_result == "rejected"

    # rollback goes back to v1
    assert c.post(f"/api/specialists/{sid}/rollback").json()["live_version"] == 1
    assert _sha(sealed) == sealed_before
    assert config.runs_dir() == orch.dir.parent
