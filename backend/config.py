"""Settings from .env plus the YAML files in config/. Nothing else reads environment variables."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
load_dotenv(ROOT / ".env")


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


@lru_cache
def _models_file() -> dict:
    return yaml.safe_load((CONFIG_DIR / "models.yaml").read_text())


def models() -> dict:
    return _models_file()["roles"]


def no_thinking_extra_body() -> dict:
    return _models_file()["no_thinking_extra_body"]


@lru_cache
def pricing() -> dict:
    return yaml.safe_load((CONFIG_DIR / "pricing.yaml").read_text())


@lru_cache
def psc_categories() -> dict:
    return yaml.safe_load((CONFIG_DIR / "psc_categories.yaml").read_text())


@lru_cache
def datasets() -> dict:
    return yaml.safe_load((CONFIG_DIR / "datasets.yaml").read_text())["datasets"]


def model_id(role: str) -> str:
    return models()[role]["api_id"]


def token_price(api_id: str) -> dict:
    """USD per 1M tokens: {input, output, cached_input?}."""
    return pricing()["token_factory"]["per_1m_tokens"][api_id]


def serverless_hourly_usd(preset: str | None = None) -> float:
    s = pricing()["serverless_cpu"]
    p = s["presets"][preset or s["chosen_preset"]]
    compute = p["vcpus"] * s["vcpu_hour"] + p["ram_gib"] * s["ram_gib_hour"]
    disk = s["min_disk_gib"] * s["network_ssd_gib_month"] / s["hours_per_month"]
    return compute + disk


def data_dir() -> Path:
    return (ROOT / env("DATA_DIR", "./data")).resolve()


def runs_dir() -> Path:
    return (ROOT / env("RUNS_DIR", "./runs")).resolve()


def artifacts_dir() -> Path:
    return (ROOT / env("ARTIFACTS_DIR", "./artifacts")).resolve()


def app_mode() -> str:
    return env("APP_MODE", "live")


def training_backend() -> str:
    return env("TRAINING_BACKEND", "local")


def credit_budget_usd() -> float:
    return float(env("CREDIT_BUDGET_USD", "5"))


def max_repair_rounds() -> int:
    return int(env("MAX_REPAIR_ROUNDS", "3"))


def demo_monthly_volume() -> int:
    return int(env("DEMO_MONTHLY_VOLUME", "1000000"))
