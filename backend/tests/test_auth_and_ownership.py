"""Supabase token verification, and per-user ownership of specialists, keys and builds (TEAM_PLAN §2.1)."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.schemas import Label, TaskCard, Thresholds

ISS = "https://proj.supabase.co/auth/v1"


def card(name):
    return TaskCard(task_id=name, task_name=name, description="d", input_type="text", output_type="multiclass",
                    labels=[Label(name="a"), Label(name="b")], thresholds=Thresholds(primary_min=0.5, per_class_floor=0.3))


@pytest.fixture
def es256(monkeypatch):
    """A local ES256 signing key standing in for the project's JWKS."""
    from backend import auth
    priv = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")

    class _Key:
        key = priv.public_key()

    class _Client:
        def get_signing_key_from_jwt(self, token):
            return _Key()
    monkeypatch.setattr(auth, "_jwks_client", lambda: _Client())

    def make(sub="user-1", **over):
        claims = {"sub": sub, "aud": "authenticated", "iss": ISS, "exp": int(time.time()) + 600,
                  "role": "authenticated", "email": "a@example.com", **over}
        return jwt.encode(claims, priv, algorithm="ES256", headers={"kid": "k1"})
    return make


def test_verify_es256_tokens(es256):
    from backend import auth
    u = auth.verify(es256())
    assert (u.id, u.email) == ("user-1", "a@example.com")
    for bad in (es256(exp=int(time.time()) - 5), es256(aud="anon"), es256(iss="https://evil/auth/v1"),
                es256(role="service_role"), "not-a-jwt"):
        with pytest.raises(HTTPException) as e:
            auth.verify(bad)
        assert e.value.status_code == 401
    other = ec.generate_private_key(ec.SECP256R1())             # signed by a key that isn't the project's
    forged = jwt.encode({"sub": "x", "aud": "authenticated", "iss": ISS, "exp": int(time.time()) + 60}, other,
                        algorithm="ES256")
    with pytest.raises(HTTPException):
        auth.verify(forged)


def test_verify_legacy_hs256(monkeypatch):
    from backend import auth
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    tok = jwt.encode({"sub": "u2", "aud": "authenticated", "iss": ISS, "exp": int(time.time()) + 60}, "s" * 32,
                     algorithm="HS256")
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    with pytest.raises(HTTPException):
        auth.verify(tok)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "s" * 32)
    assert auth.verify(tok).id == "u2"


def test_current_user_modes(es256, monkeypatch):
    from backend import auth
    assert auth.current_user(None, None) is None                       # AUTH_REQUIRED=false: anonymous allowed
    assert auth.current_user(f"Bearer {es256()}", None).id == "user-1"
    assert auth.current_user(None, es256(sub="q")).id == "q"           # ?access_token= for SSE
    with pytest.raises(HTTPException):
        auth.current_user("Basic abc", None)
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    with pytest.raises(HTTPException) as e:
        auth.current_user(None, None)
    assert e.value.status_code == 401


@pytest.fixture
def app_users(tmp_env, monkeypatch):
    """The main app with tokens 'alice' / 'bob' standing for signed-in users of those ids."""
    from backend import auth, main
    monkeypatch.setattr(auth, "verify", lambda token: auth.User(id=token))
    return TestClient(main.app)


def H(user):
    return {"Authorization": f"Bearer {user}"}


def test_specialist_visibility_and_ids(app_users):
    from backend.versions import registry
    demo = registry.get_or_create(card("Shared Demo"))                      # no owner: public demo
    alice = registry.get_or_create(card("Alice Thing"), user_id="alice")
    bob_same_name = registry.get_or_create(card("Alice Thing"), user_id="bob")
    assert bob_same_name.specialist_id != alice.specialist_id and bob_same_name.user_id == "bob"
    assert registry.get_or_create(card("Alice Thing"), user_id="alice").specialist_id == alice.specialist_id
    c = app_users
    bob_sees = {s["specialist_id"] for s in c.get("/api/specialists", headers=H("bob")).json()}
    assert bob_sees == {demo.specialist_id, bob_same_name.specialist_id}
    assert c.get(f"/api/specialists/{alice.specialist_id}", headers=H("bob")).status_code == 404
    mine = c.get(f"/api/specialists/{alice.specialist_id}", headers=H("alice")).json()
    assert mine["owned"] is True
    assert c.get(f"/api/specialists/{demo.specialist_id}", headers=H("bob")).json()["owned"] is False


def test_demo_keys_are_per_user(app_users):
    from backend.versions import registry
    demo = registry.get_or_create(card("Shared Demo"))
    c = app_users
    ka = c.post(f"/api/specialists/{demo.specialist_id}/keys", headers=H("alice")).json()["api_key"]
    kb = c.post(f"/api/specialists/{demo.specialist_id}/keys", headers=H("bob")).json()["api_key"]
    ka2 = c.post(f"/api/specialists/{demo.specialist_id}/keys", headers=H("alice")).json()["api_key"]
    v = registry.load(demo.specialist_id)
    assert not registry.key_matches(v, ka)                  # alice's regenerate revoked only her old key
    assert registry.key_matches(v, kb) and registry.key_matches(v, ka2)
    view = c.get(f"/api/specialists/{demo.specialist_id}", headers=H("bob")).json()
    assert len(view["keys"]) == 1 and view["has_key"]       # bob sees only his own key records


def test_edit_rights(app_users, monkeypatch):
    from backend.versions import registry
    demo = registry.get_or_create(card("Shared Demo"))
    alice = registry.get_or_create(card("Alice Thing"), user_id="alice")
    c = app_users
    assert c.post(f"/api/specialists/{alice.specialist_id}/rollback", headers=H("bob")).status_code == 404
    assert c.post(f"/api/specialists/{alice.specialist_id}/rollback", headers=H("alice")).status_code == 409  # allowed, no live version
    assert c.post(f"/api/specialists/{demo.specialist_id}/rollback").status_code == 409     # local dev: demo editable
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    assert c.post(f"/api/specialists/{demo.specialist_id}/rollback", headers=H("alice")).status_code == 403
    assert c.get("/api/specialists").status_code == 401


def test_builds_and_runs_hidden_from_other_users(app_users, monkeypatch):
    import json
    from backend.versions import registry
    d = app_users
    runs = registry.config.runs_dir()
    for rid in ("alice-run", "demo-run"):
        (runs / rid).mkdir()
        (runs / rid / "run_state.json").write_text(json.dumps({"run_id": rid, "task_id": "t", "stage": "end",
                                                               "budget_usd": 1, "started": 1, "updated": 2,
                                                               "status": "done"}))
    monkeypatch.setattr(registry, "run_owners", lambda: {"alice-run": "alice"})
    monkeypatch.setattr(registry, "run_owner", lambda r: (True, "alice") if r == "alice-run" else (False, None))
    assert {b["run_id"] for b in d.get("/api/builds", headers=H("bob")).json()} == {"demo-run"}
    assert {b["run_id"] for b in d.get("/api/builds", headers=H("alice")).json()} == {"alice-run", "demo-run"}
    assert d.get("/api/runs/alice-run/state", headers=H("bob")).status_code == 404
    assert d.get("/api/runs/alice-run/state", headers=H("alice")).status_code == 200
    assert d.get("/api/runs/demo-run/state").status_code == 200
    assert d.post("/api/builds/alice-run/cancel", headers=H("bob")).status_code == 404
