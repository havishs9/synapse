"""Per-specialist API keys (403 for another specialist's key, revoked keys fail) and the version gate."""
import json

from fastapi.testclient import TestClient

from backend.schemas import TaskCard, Thresholds, Label


def card(name):
    return TaskCard(task_id=name, task_name=name, description="d", input_type="text", output_type="multiclass",
                    labels=[Label(name="a"), Label(name="b")], thresholds=Thresholds(primary_min=0.5, per_class_floor=0.3))


def test_key_scoping_and_revocation(tmp_env):
    from backend.serving.server import create_app
    from backend.versions import registry
    v1, v2 = registry.get_or_create(card("Spec One")), registry.get_or_create(card("Spec Two"))
    k1, k2 = registry.create_key(v1), registry.create_key(v2)
    client = TestClient(create_app())
    url = f"/v1/specialists/{v1.specialist_id}/versions"
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"Authorization": f"Bearer {k1}"}).status_code == 200
    assert client.get(url, headers={"Authorization": f"Bearer {k2}"}).status_code == 403
    new = registry.create_key(registry.load(v1.specialist_id))      # regenerate revokes the old key
    assert client.get(url, headers={"Authorization": f"Bearer {k1}"}).status_code == 403
    assert client.get(url, headers={"Authorization": f"Bearer {new}"}).status_code == 200
    stored = json.loads(registry.path(v1.specialist_id).read_text())
    assert all(new not in json.dumps(k) and k1 not in json.dumps(k) for k in stored["api_keys"])  # only hashes
    assert client.get("/admin/specialists/x/keys").status_code in (403, 405)


def test_version_gate():
    from backend.agents.evaluator_agent import version_gate
    c = card("g")
    good = {"primary": 0.7, "per_class": {"a": {"recall": 0.8}, "b": {"recall": 0.6}}}
    assert version_gate(c, good, None)[0]
    assert not version_gate(c, {**good, "primary": 0.4}, None)[0]                     # below target
    floor = {"primary": 0.8, "per_class": {"a": {"recall": 0.9}, "b": {"recall": 0.2}}}
    ok, why = version_gate(c, floor, None)
    assert not ok and "b" in why                                                         # breaks per-class floor
    assert not version_gate(c, good, {"primary": 0.75})[0]                              # doesn't beat v1
    assert version_gate(c, {**good, "primary": 0.8}, {"primary": 0.75})[0]
