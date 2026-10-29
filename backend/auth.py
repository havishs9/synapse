"""Supabase Auth on the server: verify the `Authorization: Bearer <access token>` sent by the frontend.

Tokens are checked against the project's signing keys (SUPABASE_URL/auth/v1/.well-known/jwks.json, ES256/RS256);
projects still on the legacy shared secret are checked with SUPABASE_JWT_SECRET (HS256).
AUTH_REQUIRED=false (default until the login screens ship) lets calls without a token through as `None`
(local dev, replay); a token that is sent is always verified.
Specialist prediction routes don't use this: they keep their per-specialist API keys.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from fastapi import Header, HTTPException, Query

from backend import config

_jwks = None
_lock = threading.Lock()


@dataclass(frozen=True)
class User:
    id: str
    email: str | None = None


def auth_required() -> bool:
    return (config.env("AUTH_REQUIRED", "false") or "").lower() in ("1", "true", "yes")


def _issuer() -> str:
    url = (config.env("SUPABASE_URL") or "").rstrip("/")
    if not url:
        raise HTTPException(503, "Sign-in isn't configured on this server (SUPABASE_URL is empty).")
    return f"{url}/auth/v1"


def _jwks_client():
    global _jwks
    with _lock:
        if _jwks is None:
            import jwt
            _jwks = jwt.PyJWKClient(f"{_issuer()}/.well-known/jwks.json", cache_keys=True, lifespan=3600)
        return _jwks


def verify(token: str) -> User:
    """Claims of a valid Supabase access token as a User; raises 401 otherwise."""
    import jwt
    try:
        alg = jwt.get_unverified_header(token).get("alg")
        opts = {"audience": "authenticated", "issuer": _issuer(), "options": {"require": ["exp", "sub"]}}
        if alg == "HS256":
            secret = config.env("SUPABASE_JWT_SECRET")
            if not secret:
                raise jwt.InvalidTokenError("HS256 token but SUPABASE_JWT_SECRET is not set")
            claims = jwt.decode(token, secret, algorithms=["HS256"], **opts)
        elif alg in ("ES256", "RS256"):
            key = _jwks_client().get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=[alg], **opts)
        else:
            raise jwt.InvalidTokenError(f"unsupported algorithm {alg}")
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Your session expired. Sign in again.")
    except (jwt.InvalidTokenError, jwt.PyJWKClientError) as exc:
        raise HTTPException(401, f"Invalid sign-in token ({type(exc).__name__}).")
    if claims.get("role") not in (None, "authenticated"):
        raise HTTPException(401, "Invalid sign-in token (not a user session).")
    return User(id=claims["sub"], email=claims.get("email"))


def current_user(authorization: str | None = Header(None), access_token: str | None = Query(None)) -> User | None:
    """FastAPI dependency: the signed-in user, or None when no token is sent and AUTH_REQUIRED is off.
    `?access_token=` is accepted too, for the SSE stream (the browser's EventSource can't send headers)."""
    if not authorization and access_token:
        authorization = f"Bearer {access_token}"
    if not authorization:
        if auth_required():
            raise HTTPException(401, "Sign in to use this.")
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "Send 'Authorization: Bearer <access token>'.")
    return verify(token.strip())


def uid(user: User | None) -> str | None:
    return user.id if user else None


def can_view(spec, user: User | None) -> bool:
    """Demo specialists (no owner) are open to everyone; others only to their owner."""
    return spec.user_id is None or spec.user_id == uid(user)


def can_edit(spec, user: User | None) -> bool:
    """Rollback, deploy and similar changes: the owner only. A demo specialist can be changed only on a server
    without required sign-in (local dev), never on the public deployment."""
    if spec.user_id is None:
        return not auth_required()
    return spec.user_id == uid(user)


def require_view(spec, user: User | None) -> None:
    if not can_view(spec, user):
        raise HTTPException(404, f"No specialist '{spec.specialist_id}'.")     # don't reveal other users' ids


def require_edit(spec, user: User | None) -> None:
    require_view(spec, user)
    if not can_edit(spec, user):
        raise HTTPException(403, "Only the owner can change this specialist; demo specialists are read-only.")
