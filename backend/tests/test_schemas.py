import pytest
from pydantic import ValidationError

from backend.demo_tasks import logs_card, procurement_card
from backend.schemas import Event, TaskCard


def test_demo_cards_roundtrip(tmp_path):
    for c in (procurement_card(), logs_card()):
        p = c.write(tmp_path / f"{c.task_id}.json")
        assert TaskCard.read(p) == c


def test_schema_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        Event(ts=0, agent="Data", stage="x", message="m", surprise=1)
    with pytest.raises(ValidationError):
        Event(ts=0, agent="Nobody", stage="x", message="m")
