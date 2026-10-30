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


# The replies in docs/VIDEO_SCRIPT.md, each matching its recorded build's task card.
SCRIPTED = {
    "procurement": ("About 2 million records a month. All categories matter equally. Give me the category with a "
                    "short reason. Cloud calls are fine, but keep each answer under 50 ms.",
                    {"monthly_volume": 2_000_000, "error_preference": "balanced", "needs_reason": True,
                     "deployment": "cloud_ok", "latency_budget_ms": 50}),
    "hdfs_logs": ("Around 5 million log windows a month. Missing a real anomaly is much worse than a false alarm. "
                  "A short reason with each verdict, please. Cloud calls are fine, under 20 ms each.",
                  {"monthly_volume": 5_000_000, "error_preference": "recall_first", "needs_reason": True,
                   "deployment": "cloud_ok", "latency_budget_ms": 20}),
    "support_tickets": ("About 500k tickets a month. All intents matter equally. Just the category. Cloud is fine, "
                        "under 500 ms.",
                        {"monthly_volume": 500_000, "error_preference": "balanced", "needs_reason": False,
                         "deployment": "cloud_ok", "latency_budget_ms": 500}),
}


def test_reply_parsing_needs_no_model(monkeypatch):
    monkeypatch.setattr(product, "llm", lambda: pytest.fail("the scripted replies must parse without Nemotron"))
    for task, (reply, want) in SCRIPTED.items():
        assert product.parse_reply(reply, product.base_card(task)) == want, task
    logs = product.base_card("hdfs_logs")
    assert product._rules_reply("False alarms are worse than missing one; no latency limit; our own servers only, $3",
                                True) == {"error_preference": "precision_first", "latency_budget_ms": None,
                                          "deployment": "offline", "build_budget_usd": 3}
    assert product._rules_reply("respond within 2 seconds, without a reason", False) == {
        "latency_budget_ms": 2000, "needs_reason": False}
    assert logs.output_type == "binary"


def test_conversational_intake(tmp_env, monkeypatch):
    """Data step first (the recorded search, then the vetted dataset to approve), then one message of questions,
    then one free-text reply → task card that matches the recorded build's settings."""
    import backend.main as main
    monkeypatch.setattr(product, "_llm_intake", lambda text, samples: None)
    c = TestClient(main.app)
    r = c.post("/api/intake/start", json={"text": "Route support tickets to the right team"}).json()
    assert r["task_id"] == "support_tickets"
    assert "Tavily web search" in r["message"] and "Banking77" in r["message"] and r["message"].endswith("OK to train on it?")
    assert r["data_step"]["search"]["left_out"] and r["data_step"]["dataset"]["license"] == "CC-BY-4.0"
    assert 1 <= r["ask"].count("?") <= 7                                      # DECISION D5
    reply, want = SCRIPTED["support_tickets"]
    r = c.post("/api/intake/card", json={"task_id": "support_tickets", "reply": reply}).json()
    assert {k: r["card"][k] for k in want} == want and r["answers"]["needs_reason"] is False
    assert r["ack"].startswith("Got it: 500k a month") and r["plan_changes"][0]["question"] == "data"
    r = c.post("/api/intake/card", json={"task_id": "support_tickets", "answers": r["answers"]}).json()
    assert r["ack"] is None and r["card"]["latency_budget_ms"] == 500           # editing the card keeps the reply's answers


def test_search_summary_counts_reasons():
    rej = [{"reason": 'license "cc-by-nc-4.0" isn\'t on the allowlist'}] * 2 + [{"reason": "inputs or labels don't match the task"}]
    s = product.search_summary({"hub_queries": ["a", "b"], "web_query": "q", "candidates": 3}, rej, 0)
    assert s == ("I searched Hugging Face for “a” and “b” plus a Tavily web search: 3 candidate datasets, none fit: "
                 "2 have licenses we can't use (non-commercial or unknown) and 1 has inputs or labels that don't match.")
    assert "none of the results" in product.search_summary({"hub_queries": ["x"], "candidates": 0}, [], 0)


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


def test_improve_on_a_server_without_the_files(fixture_env, monkeypatch):
    """With Object Storage, a server that didn't run the build fetches the run folder and the live bundle, and the
    improve run is uploaded so the next server (or the next improve) can use it."""
    import shutil
    from backend import config
    from backend.improve import Improver
    from backend.storage import objects
    from backend.versions import registry
    monkeypatch.setenv("OBJECT_STORAGE_BACKEND", f"local:{fixture_env / 'bucket'}")
    orch, sid = _build_v1()
    v = registry.load(sid)
    registry.live(v).sealed_metrics["primary"] = 0.01
    registry.save(v)
    shutil.rmtree(orch.dir)                                       # this server never had the build's files
    shutil.rmtree(registry.bundle_dir(sid, 1))
    rows = [{"input": "PURCHASE OF LAPTOP SERVER", "predicted_label": "Medical", "corrected_label": "IT",
             "timestamp": 0.0, "source": "user"}]
    imp = Improver(sid, rows)
    res = imp.run()
    assert imp.state.status == "done", imp.state.message
    assert res["deployed"] is True and (config.runs_dir() / "fixture-v1" / "sealed" / "test.jsonl").exists()
    assert objects.list_keys(objects.run_prefix(None, imp.run_id))      # the improve run went to the bucket
