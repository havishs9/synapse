"""Live data sourcing (backend/data_sourcing.py) with the network and the LLM mocked: license checks, column
picking, intake for a task outside the demo datasets, and full builds on a Hugging Face dataset (with synthetic gap
fill) and on synthetic data only."""
import json
import random

import pytest
from fastapi.testclient import TestClient

from backend import data_sourcing as ds
from backend.routes import product

SPAM = ["win a free prize now", "claim your cash reward", "urgent click this link", "you won a gift card",
        "free entry to win", "limited offer call now"]
HAM = ["see you at lunch", "running late, be there soon", "can you pick up milk", "thanks for dinner",
       "meeting moved to 3pm", "call me when you are home"]


def test_license_allowlist():
    assert ds.license_ok("cc-by-4.0") and ds.license_ok("MIT") and ds.license_ok("apache-2.0")
    for bad in ("unknown", "other", "cc-by-nc-4.0", "cc-by-nd-4.0", "gpl"):
        assert not ds.license_ok(bad)
    assert ds.license_of({"cardData": {"license": ["cc-by-4.0"]}}) == "cc-by-4.0"
    assert ds.license_of({"tags": ["task_categories:text-classification", "license:MIT"]}) == "mit"
    assert ds.license_of({}) == "unknown"


def test_pick_columns():
    feats = {"idx": {"_type": "Value", "dtype": "int32"}, "sms": {"_type": "Value", "dtype": "string"},
             "label": {"_type": "ClassLabel", "names": ["ham", "spam"]}}
    assert ds._pick_columns(feats, [{"sms": "hi", "label": 0}]) == ("sms", "label", ["ham", "spam"])
    feats = {"body": {"_type": "Value", "dtype": "string"}, "id": {"_type": "Value", "dtype": "string"},
             "category": {"_type": "Value", "dtype": "string"}}
    rows = [{"body": "long message text here", "id": "a1", "category": c} for c in ("x", "y", "x")]
    assert ds._pick_columns(feats, rows) == ("body", "category", None)
    feats["genres"] = [{"_type": "Value", "dtype": "string"}]          # a Sequence column comes back as a list
    assert ds._pick_columns(feats, rows) == ("body", "category", None)


def test_unreadable_candidate_does_not_fail_the_search(monkeypatch):
    def boom(url, params=None, timeout=20):
        raise ValueError("unexpected viewer response")
    monkeypatch.setattr(ds, "_get", boom)
    out = ds.inspect({"id": "someone/anime", "cardData": {"license": "mit"}})
    assert out["usable"] is False and "ValueError" in out["reason"]


def test_data_option_is_checked():
    with pytest.raises(ds.SourcingError):
        ds.data_source_from({"kind": "hf", "name": "someone/data", "license": "cc-by-nc-4.0"})
    with pytest.raises(ds.SourcingError):
        ds.data_source_from({"kind": "hf", "name": "../../etc", "license": "mit"})
    assert ds.data_source_from({"kind": "synthetic"})["kind"] == "synthetic"


def _fake_rows(n=800, seed=0):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        lab = rng.choice(["ham", "spam"])
        words = rng.sample(SPAM if lab == "spam" else HAM, 2)
        out.append({"id": f"train-{i}", "text": f"{' and '.join(words)} {i}", "source_label": lab})
    return out


def _fake_synthetic(card, labels, per_label, llm, emit):
    return [{"id": f"syn-{lab}-{i}", "text": f"{lab} example {lab} number {i}", "label": lab, "synthetic": True}
            for lab in labels for i in range(per_label)]


def _custom_card(labels, binary):
    d = {"task_name": "Spam Detector" if binary else "Message Sorter", "description": "Flag spam text messages.",
         "output_type": "binary" if binary else "multiclass",
         "labels": [{"name": n, "definition": f"a {n} message"} for n in labels],
         "positive_label": labels[0] if binary else ""}
    return ds.card_from_draft(d, ["free prize, call now"])


def _build(card):
    from backend.orchestrator import Options, Orchestrator
    card = card.model_copy(update={"latency_budget_ms": 5000})
    orch = Orchestrator(card, run_id=f"{card.task_id}-run", options=Options(
        families=["J", "A"], limit_per_family=2, repair=False, cascade=False, seeds=False, baseline_n=20, max_eval_llm=20))
    orch.run()
    assert orch.state.status == "done", (orch.dir / "error.log").read_text() if (orch.dir / "error.log").exists() else orch.state.message
    return orch.dir


def test_build_on_a_hub_dataset_with_gap_fill(fixture_env, monkeypatch):
    monkeypatch.setattr(ds, "hub_info", lambda did: {"cardData": {"license": "cc-by-4.0"}})
    monkeypatch.setattr(ds, "fetch_rows", lambda src, n: _fake_rows())
    monkeypatch.setattr(ds, "generate_synthetic", _fake_synthetic)
    card = _custom_card(["spam", "ham", "phishing"], binary=False)
    card = ds.apply_option(card, {"kind": "hf", "name": "someone/sms-spam", "url": "https://huggingface.co/datasets/someone/sms-spam",
                                  "license": "cc-by-4.0", "config": "default", "splits": ["train"], "text_column": "sms",
                                  "label_column": "label", "label_names": ["ham", "spam"],
                                  "label_map": {"ham": "ham", "spam": "spam"}, "gap_labels": ["phishing"]})
    d = _build(card)
    manifest = json.loads((d / "dataset_manifest.json").read_text())
    names = [s["name"] for s in manifest["sources"]]
    assert names[0] == "someone/sms-spam" and manifest["sources"][1]["is_synthetic"]
    from backend.sealed import _sealed_path
    test = [json.loads(line) for line in _sealed_path(d).open()]
    assert test and all(not r.get("synthetic") for r in test)     # gap-fill rows never reach the sealed test
    val = [json.loads(line) for line in (d / "val.jsonl").open()]
    assert all(not r.get("synthetic") for r in val)
    train = [json.loads(line) for line in (d / "train.jsonl").open()]
    assert any(r.get("synthetic") and r["label"] == "phishing" for r in train)
    rc = json.loads((d / "report_card.json").read_text())
    assert rc["real_vs_synthetic"]["real_validation"] is not None


def test_build_on_synthetic_data_only(fixture_env, monkeypatch):
    monkeypatch.setattr(ds, "generate_synthetic", _fake_synthetic)
    card = ds.apply_option(_custom_card(["spam", "ham"], binary=True), {"kind": "synthetic"})
    assert card.output_type == "binary" and card.positive_definition == "spam"
    d = _build(card)
    manifest = json.loads((d / "dataset_manifest.json").read_text())
    assert [s["is_synthetic"] for s in manifest["sources"]] == [True]
    rc = json.loads((d / "report_card.json").read_text())
    assert rc["real_vs_synthetic"]["real_training_rows"] == 0 and "synthetic" in rc["real_vs_synthetic"]["note"]
    assert "all synthetic" in (d / "report_card.md").read_text()


def test_api_option_is_checked():
    ok = ds.data_source_from({"kind": "api", "source": "wikidata", "filter": {"class": "anime_series"}})
    assert ok["license"] == "cc0-1.0" and ok["name"] == "Wikidata: anime television series"
    for bad in ({"source": "wikidata", "filter": {"class": "Q42"}}, {"source": "openlibrary", "filter": {}},
                {"source": "tvmaze", "filter": {"genre": "NotAGenre"}}):
        with pytest.raises(ds.SourcingError):
            ds.data_source_from({"kind": "api", **bad})


def test_teacher_labels_api_items():
    class Res:
        def __init__(self, text):
            self.text = text

        def json(self):
            items = [line for line in self.text.split("\n") if line[:1].isdigit()]
            return {"labels": [{"i": int(x.split(".")[0]), "label": "spam" if any(w in x for w in ("prize", "cash", "win", "free"))
                                else "ham"} for x in items] + [{"i": 0, "label": "not_a_label"}]}

    class LLM:
        def chat(self, role, messages, **kw):
            assert role == ds.cfg()["teacher_labeling_role"] and kw["response_format"]["type"] == "json_schema"
            return Res(messages[0]["content"])

    items = [{"id": f"x{i}", "text": t} for i, t in enumerate(SPAM + HAM)]
    rows = ds.teacher_label(_custom_card(["spam", "ham"], binary=True), items, LLM(), lambda *a, **k: None)
    assert len(rows) == len(items) and {r["label"] for r in rows} == {"spam", "ham"}
    assert next(r for r in rows if r["text"] == SPAM[0])["label"] == "spam"


def test_build_on_api_items(fixture_env, monkeypatch):
    rng = random.Random(3)
    items = [{"id": f"tv-{i}", "text": f"{rng.choice(SPAM if i % 2 else HAM)} #{i}"} for i in range(400)]
    monkeypatch.setattr(ds, "fetch_api", lambda src, n, preview=False: items[:n])
    monkeypatch.setattr(ds, "teacher_label", lambda card, its, llm, emit: [
        {**it, "label": "spam" if any(w in it["text"] for w in ("prize", "cash", "win", "free", "click", "offer")) else "ham"}
        for it in its])
    card = ds.apply_option(_custom_card(["spam", "ham"], binary=True),
                           {"kind": "api", "source": "tvmaze", "filter": {"genre": "", "language": ""}})
    d = _build(card)
    manifest = json.loads((d / "dataset_manifest.json").read_text())
    src = manifest["sources"][0]
    assert src["license"] == "cc-by-sa-4.0" and src["labeled_by"].startswith("teacher") and not src["is_synthetic"]
    assert "agreement" in (d / "report_card.md").read_text()


def test_infeasible_draft_is_redrafted_for_an_explicit_request(tmp_env, monkeypatch):
    import backend.main as main
    monkeypatch.setattr(product, "_llm_intake", lambda text, samples: {"build_request": True, "task_id": "none",
                                                                       "intro": "", "questions": []})
    monkeypatch.setattr(product, "_guard", lambda: None)
    good = {"feasible": True, "why_not": "", "task_name": "TV Show Recommender", "description": "Recommend shows.",
            "output_type": "binary", "labels": [{"name": "recommend", "definition": "fits"}, {"name": "skip", "definition": "no"}],
            "positive_label": "recommend", "search_queries": ["tv"], "web_query": "", "input_hint": "a show",
            "preference_question": "Which shows do you love or avoid?"}
    calls = []
    monkeypatch.setattr(ds, "draft_task", lambda text, samples, llm, insist=False: calls.append(insist) or (
        good if insist else {**good, "feasible": False, "why_not": "a recommender is retrieval"}))
    monkeypatch.setattr(ds, "find_datasets", lambda card, d, llm: {
        "options": [ds.synthetic_option(card)], "rejected": [], "searched": {"candidates": 0, "web_query": None}})
    r = TestClient(main.app).post("/api/intake/start", json={"text": "Make a model that recommends TV shows I'd like"}).json()
    assert calls == [False, True] and r["custom"]
    assert r["questions"][0]["text"] == good["preference_question"] and r["questions"][0]["free_text_first"]


def test_custom_intake(tmp_env, monkeypatch):
    import backend.main as main
    monkeypatch.setattr(product, "_llm_intake", lambda text, samples: {"task_id": "none", "intro": "", "questions": []})
    monkeypatch.setattr(product, "_guard", lambda: None)
    draft = {"feasible": True, "why_not": "", "task_name": "Spam Detector", "description": "Flag spam text messages.",
             "output_type": "binary", "labels": [{"name": "spam", "definition": "unwanted"}, {"name": "ham", "definition": "normal"}],
             "positive_label": "spam", "search_queries": ["sms spam"], "web_query": "", "input_hint": "one SMS"}
    monkeypatch.setattr(ds, "draft_task", lambda text, samples, llm: draft)
    hf = {"id": "hf:someone/sms-spam", "kind": "hf", "name": "someone/sms-spam", "url": "https://huggingface.co/datasets/someone/sms-spam",
          "license": "cc-by-4.0", "config": "default", "splits": ["train"], "text_column": "sms", "label_column": "label",
          "label_names": ["ham", "spam"], "label_map": {"ham": "ham", "spam": "spam"}, "labels": ["ham", "spam"],
          "gap_labels": [], "rows": 5000, "samples": []}
    monkeypatch.setattr(ds, "find_datasets", lambda card, d, llm: {
        "options": [hf, ds.synthetic_option(card)], "rejected": [], "searched": {"candidates": 3, "web_query": None}})
    c = TestClient(main.app)
    r = c.post("/api/intake/start", json={"text": "Make a model that flags spam texts"}).json()
    assert r["custom"] and r["task_id"].startswith("custom_") and r["data_choice"] == hf["id"]
    assert [o["kind"] for o in r["data_options"]] == ["hf", "synthetic"] and len(r["questions"]) <= 7
    body = {"task_id": r["task_id"], "card": r["card"], "data_option": r["data_options"][0], "answers": {"deployment": "offline"}}
    out = c.post("/api/intake/card", json=body).json()
    assert out["card"]["data_source"]["name"] == "someone/sms-spam" and out["card"]["deployment"] == "offline"
    assert "someone/sms-spam" in out["plan_changes"][0]["change"]
    out = c.post("/api/intake/card", json={**body, "data_option": r["data_options"][1]}).json()
    assert out["card"]["data_source"]["kind"] == "synthetic"
    bad = {**body, "data_option": {**hf, "license": "cc-by-nc-4.0"}}
    assert c.post("/api/intake/card", json=bad).status_code == 400
    assert c.post("/api/intake/card", json={**body, "card": {**r["card"], "task_id": "procurement2"}}).status_code == 400


def test_explicit_model_request_is_not_sent_to_chat(tmp_env, monkeypatch):
    """Nemotron sometimes reads "create a model for X" as a question; an explicit request still goes to intake,
    and a task with no fitting dataset is offered synthetic data."""
    import backend.main as main
    monkeypatch.setattr(product, "_llm_intake", lambda text, samples: {"build_request": False, "task_id": "none",
                                                                       "intro": "", "questions": []})
    monkeypatch.setattr(product, "_guard", lambda: None)
    draft = {"feasible": True, "why_not": "", "task_name": "Anime Recommender", "description": "Recommend anime.",
             "output_type": "binary", "labels": [{"name": "recommend", "definition": "fits my taste"},
                                                 {"name": "skip", "definition": "doesn't"}],
             "positive_label": "recommend", "search_queries": ["anime"], "web_query": "", "input_hint": "a title"}
    monkeypatch.setattr(ds, "draft_task", lambda text, samples, llm: draft)
    monkeypatch.setattr(ds, "find_datasets", lambda card, d, llm: {
        "options": [ds.synthetic_option(card)], "rejected": [], "searched": {"candidates": 5, "web_query": None}})
    c = TestClient(main.app)
    r = c.post("/api/intake/start", json={"text": "Can you create a model for recommending me anime based on my taste"}).json()
    assert r["custom"] and r["data_choice"] == "synthetic" and r["message"].startswith("I'll build an anime")
    assert c.post("/api/intake/start", json={"text": "What is a specialist?"}).json() == {"chat": True}


@pytest.fixture
def fixture_env(tmp_env, monkeypatch):
    monkeypatch.setenv("SYNAPSE_FAKE_LLM", "1")
    monkeypatch.setenv("MAX_REPAIR_ROUNDS", "1")
    return tmp_env
