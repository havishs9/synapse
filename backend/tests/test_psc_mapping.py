from backend.agents.data_agent import clean_description, psc_to_category


def test_exact_code():
    assert psc_to_category("7030") in ("IT",)          # IT software (legacy 70 family override or exact)
    assert psc_to_category("DA01") == "IT"


def test_prefix_fallback_and_legacy_override():
    assert psc_to_category("D399") == "IT"             # retired D3 family -> IT override
    assert psc_to_category(None) is None
    assert psc_to_category("") is None


def test_rnd_codes_start_with_a():
    cats = {psc_to_category(c) for c in ("AC11", "AN11", "AJ11")}
    assert cats <= {"Research and Development", None}
    assert "Research and Development" in cats


def test_boilerplate_stripped():
    assert clean_description("8500135728!SUPPORT,STRUCTURAL") == "SUPPORT,STRUCTURAL"
    assert clean_description("TH-57 SUPPORT. IGF::CT::IGF") == "TH-57 SUPPORT."
