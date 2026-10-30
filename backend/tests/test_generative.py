"""Rung G serving: generative bundles are routed to GenerativePredictor; JSON parsing of model output."""
import json

from backend.serving import generative, server
from backend.serving.generative import parse_json


def test_parse_json_variants():
    assert parse_json('{"intent": "alarm_set", "slots": {"time": "nine am"}}')["slots"] == {"time": "nine am"}
    assert parse_json('<think>\n\n</think>\n\n{"intent": "x", "slots": {}}')["intent"] == "x"
    assert parse_json("noise before {\"intent\": \"y\"} after")["intent"] == "y"
    assert parse_json("not json at all") is None
    assert parse_json("[1, 2]") is None


def test_generative_bundle_uses_generative_predictor(tmp_path, monkeypatch):
    (tmp_path / "bundle.json").write_text(json.dumps({"kind": "generative", "system_prompt": "s"}))

    class Stub:
        def __init__(self, d, llm=None):
            self.dir = d

    monkeypatch.setattr(server.registry, "ensure_bundle", lambda sid, v: tmp_path)
    monkeypatch.setattr(generative, "GenerativePredictor", Stub)
    server._cache.pop(("gen-test", 1), None)
    try:
        assert isinstance(server.predictor("gen-test", 1), Stub)
    finally:
        server._cache.pop(("gen-test", 1), None)
