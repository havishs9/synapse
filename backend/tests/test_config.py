"""Config consistency: every model role has a verified ID and a price; the PSC map is well-formed."""
from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parents[2] / "config"


def load(name):
    return yaml.safe_load((CONFIG / name).read_text())


def test_every_token_factory_role_has_verified_id_and_price():
    roles = load("models.yaml")["roles"]
    prices = load("pricing.yaml")["token_factory"]["per_1m_tokens"]
    for role, spec in roles.items():
        if "api_id" not in spec:  # local models run in-process, not on Token Factory
            continue
        assert spec["api_id"] != "VERIFY", role
        assert spec["api_id"] in prices, f"{role}: no price for {spec['api_id']}"


def test_psc_map_targets_known_categories():
    psc = load("psc_categories.yaml")
    cats = set(psc["categories"])
    assert 15 <= len(cats) <= 25
    for key in ("psc_to_category", "prefix3_to_category", "prefix2_to_category"):
        assert set(psc[key].values()) <= cats, key
    assert all(len(code) == 4 for code in psc["psc_to_category"])


def test_legacy_it_families_map_to_it():
    prefix2 = load("psc_categories.yaml")["prefix2_to_category"]
    assert prefix2["D3"] == "IT" and prefix2["70"] == "IT"
