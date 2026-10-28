"""Budget guard and response cache, with a fake OpenAI client (no network)."""
from types import SimpleNamespace

import pytest

from backend.llm_client import BudgetExceeded, LLMClient


class FakeCompletions:
    def __init__(self):
        self.calls = 0

    def create(self, **kw):
        self.calls += 1
        msg = SimpleNamespace(content='{"label": "a"}', tool_calls=None)
        usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=100, prompt_tokens_details=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=usage)


def fake_client():
    comp = FakeCompletions()
    return SimpleNamespace(chat=SimpleNamespace(completions=comp)), comp


def test_cache_hit_costs_nothing(tmp_path):
    client, comp = fake_client()
    llm = LLMClient(run_dir=tmp_path, budget_usd=1.0, cache_dir=tmp_path / "cache", client=client)
    msgs = [{"role": "user", "content": "hi"}]
    a = llm.chat("ladder_K_primary", msgs, agent="T", purpose="t")
    b = llm.chat("ladder_K_primary", msgs, agent="T", purpose="t")
    assert comp.calls == 1
    assert not a.cached and b.cached and b.cost_usd == 0 and b.list_cost_usd == a.cost_usd > 0
    assert (tmp_path / "llm_calls.jsonl").read_text().count("\n") == 2


def test_budget_guard_stops_calls(tmp_path):
    client, comp = fake_client()
    llm = LLMClient(run_dir=tmp_path, budget_usd=0.0001, cache_dir=tmp_path / "cache", client=client)
    llm.chat("main_chat_planner_teacher_baseline", [{"role": "user", "content": "1"}], agent="T", purpose="t")
    with pytest.raises(BudgetExceeded):
        llm.chat("main_chat_planner_teacher_baseline", [{"role": "user", "content": "2"}], agent="T", purpose="t")
    assert comp.calls == 1


def test_thinking_off_sends_extra_body(tmp_path):
    client, comp = fake_client()
    seen = {}
    orig = comp.create
    comp.create = lambda **kw: (seen.update(kw), orig(**kw))[1]
    llm = LLMClient(run_dir=tmp_path, budget_usd=1, cache_dir=tmp_path / "cache", client=client)
    llm.chat("ladder_K_primary", [{"role": "user", "content": "x"}], agent="T", purpose="t", thinking=False)
    assert seen["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
