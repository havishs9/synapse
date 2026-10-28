"""Shared specialist server: every specialist gets its own routes and its own API key (DECISION D3).

Public routes need that specialist's key as `Authorization: Bearer <key>`; another specialist's key gets 403.
Admin routes need SPECIALIST_ADMIN_TOKEN and are called only by the backend.
Run standalone: uvicorn backend.serving.server:app --port 8081
"""
from __future__ import annotations

import hmac
import threading
import time

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from backend import config
from backend.serving.predictor import InputError, Predictor
from backend.versions import registry


class PredictIn(BaseModel):
    input: str
    reason: bool | None = None


class BatchIn(BaseModel):
    inputs: list[str] = Field(max_length=1000)
    reason: bool = False


class LiveIn(BaseModel):
    version: int


_cache: dict[tuple[str, int], Predictor] = {}
_lock = threading.Lock()
_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        from backend.llm_client import LLMClient
        _llm = LLMClient(budget_usd=float("inf"))
    return _llm


def predictor(sid: str, version: int) -> Predictor:
    key = (sid, version)
    with _lock:
        if key not in _cache:
            _cache[key] = Predictor(registry.root() / sid / f"v{version}", llm=_get_llm())
        return _cache[key]


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing API key. Send 'Authorization: Bearer <your specialist key>'.")
    return authorization.split(" ", 1)[1].strip()


def _specialist(sid: str):
    if not registry.path(sid).exists():
        raise HTTPException(404, f"No specialist '{sid}'.")
    return registry.load(sid)


def require_key(sid: str, authorization: str | None = Header(None)):
    key = _bearer(authorization)
    v = _specialist(sid)
    if not registry.key_matches(v, key):
        raise HTTPException(403, "This API key isn't valid for this specialist (wrong specialist, or revoked).")
    return v


def require_admin(authorization: str | None = Header(None)):
    token = config.env("SPECIALIST_ADMIN_TOKEN") or ""
    if not token or not hmac.compare_digest(_bearer(authorization), token):
        raise HTTPException(403, "Admin token required.")


def _predict(v, version: int, texts: list[str], reason):
    if not any(r.version == version for r in v.versions):
        raise HTTPException(404, f"{v.specialist_id} has no version {version}.")
    rec = next(r for r in v.versions if r.version == version)
    if rec.gate_result == "rejected":
        raise HTTPException(409, f"v{version} was rejected by the version gate and is not served.")
    try:
        preds = predictor(v.specialist_id, version).predict(texts, with_reason=reason)
    except InputError as exc:
        raise HTTPException(422, str(exc))
    return {"specialist_id": v.specialist_id, "version": version, "predictions": preds}


def _live_version(v) -> int:
    rec = registry.live(v)
    if rec is None:
        raise HTTPException(503, "This specialist has no live version yet.")
    return rec.version


router = APIRouter()


@router.get("/health")
def health():
    return {"ok": True, "specialists": len(registry.list_specialists()), "ts": time.time()}


@router.post("/v1/specialists/{sid}/predict")
def predict_live(sid: str, body: PredictIn, v=Depends(require_key)):
    out = _predict(v, _live_version(v), [body.input], body.reason)
    pred = out.pop("predictions")[0]
    return {**out, **pred}


@router.post("/v1/specialists/{sid}/predict_batch")
def predict_batch(sid: str, body: BatchIn, v=Depends(require_key)):
    return _predict(v, _live_version(v), body.inputs, body.reason)


@router.post("/v1/specialists/{sid}/v{version}/predict")
def predict_pinned(sid: str, version: int, body: PredictIn, v=Depends(require_key)):
    out = _predict(v, version, [body.input], body.reason)
    pred = out.pop("predictions")[0]
    return {**out, **pred}


@router.get("/v1/specialists/{sid}/versions")
def versions(sid: str, v=Depends(require_key)):
    return {"specialist_id": sid, "versions": [
        {"version": r.version, "live": r.live, "gate_result": r.gate_result, "created": r.created,
         "primary": r.sealed_metrics.get("primary")} for r in v.versions]}


# ---- admin -----------------------------------------------------------------------
admin = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


@admin.post("/specialists/{sid}/reload")
def reload(sid: str):
    with _lock:
        for k in [k for k in _cache if k[0] == sid]:
            _cache.pop(k)
    return {"ok": True}


@admin.post("/specialists/{sid}/live")
def set_live(sid: str, body: LiveIn):
    registry.set_live(_specialist(sid), body.version)
    return {"ok": True}


@admin.post("/specialists/{sid}/keys")
def create_key(sid: str):
    return {"api_key": registry.create_key(_specialist(sid))}


@admin.delete("/specialists/{sid}/keys/{key_id}")
def revoke(sid: str, key_id: str):
    registry.revoke_key(_specialist(sid), key_id)
    return {"ok": True}


def create_app() -> FastAPI:
    app = FastAPI(title="Synapse specialist server")
    app.include_router(router)
    app.include_router(admin)
    return app


app = create_app()
