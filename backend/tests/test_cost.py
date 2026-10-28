import pytest

from backend import config
from backend import metrics as M
from backend.llm_client import call_cost_usd


def test_token_cost_matches_price_table():
    api = config.model_id("main_chat_planner_teacher_baseline")
    p = config.token_price(api)
    assert call_cost_usd(api, 1_000_000, 0) == pytest.approx(p["input"])
    assert call_cost_usd(api, 0, 1_000_000) == pytest.approx(p["output"])
    # cached prompt tokens use the cached rate
    assert call_cost_usd(api, 1_000_000, 0, cached_tokens=1_000_000) == pytest.approx(p["cached_input"])


def test_cpu_cost_formula():
    hourly = config.serverless_hourly_usd()
    cost, f = M.cpu_cost_per_1m(1000.0)              # 1M items at 1000/s = 1000 s
    assert cost == pytest.approx(hourly * 1000 / 3600)
    assert f["throughput_per_s"] == 1000.0


def test_serverless_hourly_from_components():
    s = config.pricing()["serverless_cpu"]
    pr = s["presets"][s["chosen_preset"]]
    expected = pr["vcpus"] * s["vcpu_hour"] + pr["ram_gib"] * s["ram_gib_hour"] + \
        s["disk_gib"] * s["network_ssd_gib_month"] / s["hours_per_month"]
    assert s["disk_gib"] >= s["min_disk_gib"]
    assert config.serverless_hourly_usd() == pytest.approx(expected)
