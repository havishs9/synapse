"""Specialist registry: specialists, versions, API keys (hashed), live version, builds list.

Records live in Postgres (Supabase, `supabase/migrations/`) when SUPABASE_DB_URL is set, else in local files
(the local/replay fallback):
  ARTIFACTS_DIR/specialists/<specialist_id>/versions.json
  ARTIFACTS_DIR/synapse.sqlite  (list of runs)
Artifact bundles stay on disk under ARTIFACTS_DIR/specialists/<specialist_id>/v<n>/{model.joblib, bundle.json}
until Object Storage lands (docs/TEAM_PLAN.md §2.2).

Ownership: a specialist's `user_id` is its owner; None means a public demo specialist (or a local build without
login). Every signed-in user may use a demo specialist and gets their own key for it.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from backend import config
from backend.schemas import ApiKeyRecord, TaskCard, VersionRecord, Versions
from backend.storage import db as pg

# 8 accessible hues for specialist identity (DESIGN.md); the main model stays neutral.
PALETTE = ["#2F6FDE", "#0E8F6E", "#C2410C", "#7C3AED", "#B4235A", "#0F766E", "#A16207", "#4338CA"]
CACHE_S = 15.0       # Postgres reads are cached this long per process; a revoked key stops working within it
_BUILD_STATUS = {"running": "running", "done": "done", "failed": "failed", "stopped_budget": "failed",
                 "queued": "queued", "cancelled": "cancelled"}


def root() -> Path:
    d = config.artifacts_dir() / "specialists"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bundle_dir(sid: str, version: int) -> Path:
    return root() / sid / f"v{version}"


# ---- runs (sidebar list) -----------------------------------------------------------
def db() -> sqlite3.Connection:
    config.artifacts_dir().mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.artifacts_dir() / "synapse.sqlite")
    c.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, task_id TEXT, kind TEXT, status TEXT, "
              "created REAL, specialist_id TEXT)")
    return c


def record_run(run_id: str, task_id: str, kind: str, status: str, specialist_id: str | None = None,
               task_name: str | None = None, user_id: str | None = None, spend_usd: float | None = None,
               budget_usd: float | None = None, message: str | None = None, version: int | None = None,
               deployed: bool | None = None) -> None:
    if pg.enabled():
        try:
            _pg_record_run(run_id, task_id, kind, status, specialist_id, task_name, user_id, spend_usd, budget_usd,
                           message, version, deployed)
        except Exception as exc:     # bookkeeping must never stop a build; the run folder stays the source of truth
            print(f"[registry] couldn't record build {run_id} in Postgres: {type(exc).__name__}: {exc}", flush=True)
        return
    with db() as c:
        c.execute("INSERT INTO runs VALUES (?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET status=excluded.status, "
                  "specialist_id=COALESCE(excluded.specialist_id, runs.specialist_id)",
                  (run_id, task_id, kind, status, time.time(), specialist_id))


def _pg_record_run(run_id, task_id, kind, status, specialist_id, task_name, user_id, spend_usd, budget_usd, message,
                   version, deployed) -> None:
    st = _BUILD_STATUS.get(status, "failed")
    with pg.conn() as c:
        c.execute("""
            insert into builds (run_id, user_id, kind, task_id, task_name, status, specialist_id, spend_usd,
                                budget_usd, message, version, deployed, started_at, finished_at)
            values (%(run_id)s, %(user_id)s, %(kind)s, %(task_id)s, %(task_name)s, %(st)s, %(sid)s,
                    coalesce(%(spend)s, 0), %(budget)s, coalesce(%(msg)s, ''), %(version)s, %(deployed)s,
                    case when %(st)s = 'running' then now() end,
                    case when %(st)s in ('done', 'failed', 'cancelled') then now() end)
            on conflict (run_id) do update set
                status = excluded.status,
                specialist_id = coalesce(excluded.specialist_id, builds.specialist_id),
                spend_usd = coalesce(%(spend)s, builds.spend_usd),
                budget_usd = coalesce(excluded.budget_usd, builds.budget_usd),
                message = coalesce(%(msg)s, builds.message),
                version = coalesce(excluded.version, builds.version),
                deployed = coalesce(excluded.deployed, builds.deployed),
                started_at = coalesce(builds.started_at, excluded.started_at),
                finished_at = coalesce(excluded.finished_at, builds.finished_at),
                updated_at = now()""",
                  {"run_id": run_id, "user_id": user_id, "kind": kind, "task_id": task_id,
                   "task_name": task_name or task_id, "st": st, "sid": specialist_id, "spend": spend_usd,
                   "budget": budget_usd, "msg": message, "version": version, "deployed": deployed})


def list_runs(user_id: str | None = None) -> list[dict]:
    if pg.enabled():
        with pg.conn() as c:
            rows = c.execute("select run_id, task_id, kind, status, extract(epoch from created_at)::float8 as created, "
                             "specialist_id from builds where user_id is not distinct from %s "
                             "order by created_at desc", (user_id,)).fetchall()
        return [dict(r) for r in rows]
    with db() as c:
        rows = c.execute("SELECT run_id, task_id, kind, status, created, specialist_id FROM runs ORDER BY created DESC")
        return [dict(zip(("run_id", "task_id", "kind", "status", "created", "specialist_id"), r)) for r in rows]


def run_owners() -> dict[str, str | None]:
    """run_id -> owner for every build recorded in Postgres (empty without a database)."""
    if not pg.enabled():
        return {}
    with pg.conn() as c:
        return {r["run_id"]: r["user_id"] for r in c.execute("select run_id, user_id::text as user_id from builds")}


def run_owner(run_id: str) -> tuple[bool, str | None]:
    """(known, user_id) for a run. Runs with no record (recorded demo runs, local files) are public."""
    if not pg.enabled():
        return False, None
    with pg.conn() as c:
        r = c.execute("select user_id::text as user_id from builds where run_id = %s", (run_id,)).fetchone()
    return (True, r["user_id"]) if r else (False, None)


# ---- specialists ---------------------------------------------------------------------
def monogram(name: str) -> str:
    words = re.findall(r"[A-Za-z]+", name)
    return (words[0][0] + (words[1][0] if len(words) > 1 else words[0][1])).upper() if words else "SP"


def path(sid: str) -> Path:
    """versions.json of a specialist in the local-files store."""
    return root() / sid / "versions.json"


_cache: dict[str, tuple[float, Versions]] = {}
_cache_lock = threading.Lock()


def _invalidate(sid: str | None = None) -> None:
    with _cache_lock:
        if sid is None:
            _cache.clear()
        else:
            _cache.pop(sid, None)


def exists(sid: str) -> bool:
    if pg.enabled():
        try:
            load(sid)
            return True
        except KeyError:
            return False
    return path(sid).exists()


def _pg_load(sid: str) -> Versions:
    with pg.conn() as c:
        s = c.execute("select specialist_id, user_id::text as user_id, display_name, monogram, color, task_id, "
                      "api_route from specialists where specialist_id = %s", (sid,)).fetchone()
        if not s:
            raise KeyError(sid)
        vers = c.execute("select version, run_id, sealed_metrics, gate_result, reason, artifact_uri, candidate, live, "
                         "extract(epoch from created_at)::float8 as created from versions where specialist_id = %s "
                         "order by version", (sid,)).fetchall()
        keys = c.execute("select key_id, hash, user_id::text as user_id, extract(epoch from created_at)::float8 as "
                         "created, extract(epoch from revoked_at)::float8 as revoked from api_keys "
                         "where specialist_id = %s order by created_at", (sid,)).fetchall()
    return Versions(**s, versions=[VersionRecord(**r) for r in vers], api_keys=[ApiKeyRecord(**k) for k in keys])


def load(sid: str) -> Versions:
    """Raises KeyError if there is no such specialist."""
    if not pg.enabled():
        if not path(sid).exists():
            raise KeyError(sid)
        return Versions.read(path(sid))
    with _cache_lock:
        hit = _cache.get(sid)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1].model_copy(deep=True)
    v = _pg_load(sid)
    with _cache_lock:
        _cache[sid] = (time.time(), v)
    return v.model_copy(deep=True)


def save(v: Versions) -> None:
    if not pg.enabled():
        v.write(path(v.specialist_id))
        return
    sid = v.specialist_id
    with pg.conn() as c:
        c.execute("""insert into specialists (specialist_id, user_id, display_name, monogram, color, task_id, api_route)
                     values (%s, %s, %s, %s, %s, %s, %s)
                     on conflict (specialist_id) do update set display_name = excluded.display_name,
                       monogram = excluded.monogram, color = excluded.color, task_id = excluded.task_id,
                       api_route = excluded.api_route""",
                  (sid, v.user_id, v.display_name, v.monogram, v.color, v.task_id, v.api_route))
        c.execute("update versions set live = false where specialist_id = %s and live", (sid,))
        for r in v.versions:
            c.execute("""insert into versions (specialist_id, version, run_id, sealed_metrics, gate_result, reason,
                                               artifact_uri, candidate, live, created_at)
                         values (%s, %s, %s, %s, %s, %s, %s, %s, %s, to_timestamp(%s))
                         on conflict (specialist_id, version) do update set gate_result = excluded.gate_result,
                           reason = excluded.reason, live = excluded.live, artifact_uri = excluded.artifact_uri,
                           sealed_metrics = excluded.sealed_metrics""",
                      (sid, r.version, r.run_id, json.dumps(r.sealed_metrics), r.gate_result, r.reason,
                       r.artifact_uri, r.candidate, r.live, r.created))
        for k in v.api_keys:
            c.execute("""insert into api_keys (key_id, specialist_id, user_id, hash, created_at, revoked_at)
                         values (%s, %s, %s, %s, to_timestamp(%s), to_timestamp(%s))
                         on conflict (key_id) do update set revoked_at = excluded.revoked_at""",
                      (k.key_id, sid, k.user_id, k.hash, k.created, k.revoked))
    _invalidate(sid)


def visible(v: Versions, user_id: str | None) -> bool:
    """Demo specialists (no owner) are visible to everyone; others only to their owner."""
    return v.user_id is None or v.user_id == user_id


def list_specialists(user_id: str | None = None, everyone: bool = False) -> list[Versions]:
    """Specialists `user_id` can see (their own plus the demo ones), or all of them with everyone=True."""
    if pg.enabled():
        with pg.conn() as c:
            q = "select specialist_id from specialists"
            rows = c.execute(q + " order by created_at") if everyone else \
                c.execute(q + " where user_id is null or user_id = %s order by created_at", (user_id,))
            ids = [r["specialist_id"] for r in rows.fetchall()]
        return [load(i) for i in ids]
    out = [Versions.read(p) for p in sorted(root().glob("*/versions.json"))]
    return out if everyone else [v for v in out if visible(v, user_id)]


def get_or_create(card: TaskCard, user_id: str | None = None) -> Versions:
    """The caller's specialist for this task (by name). Another user's specialist with the same name gets a
    separate id with a suffix, so builds never add versions to someone else's specialist."""
    base = re.sub(r"[^a-z0-9]+", "-", card.task_name.lower()).strip("-") or "specialist"
    for sid in (base, f"{base}-{(user_id or 'local')[:8]}"):
        if exists(sid):
            v = load(sid)
            if v.user_id == user_id:
                return v
            continue
        used = {s.color for s in list_specialists(user_id)}
        color = next((c for c in PALETTE if c not in used), PALETTE[len(used) % len(PALETTE)])
        v = Versions(specialist_id=sid, display_name=card.task_name, monogram=monogram(card.task_name), color=color,
                     task_id=card.task_id, api_route=f"/v1/specialists/{sid}/predict", user_id=user_id)
        save(v)
        return v
    raise RuntimeError(f"no free specialist id for {base!r}")


def live(v: Versions) -> VersionRecord | None:
    return next((r for r in v.versions if r.live), None)


def add_version(v: Versions, run_id: str, bundle_dir: Path, sealed_metrics: dict, deploy: bool, reason: str,
                candidate: str) -> VersionRecord:
    n = max((r.version for r in v.versions), default=0) + 1
    dest = root() / v.specialist_id / f"v{n}"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(bundle_dir, dest)
    rec = VersionRecord(version=n, run_id=run_id, sealed_metrics=sealed_metrics,
                        gate_result="deployed" if deploy else "rejected", reason=reason,
                        artifact_uri=f"artifacts/specialists/{v.specialist_id}/v{n}", created=time.time(),
                        candidate=candidate)
    if deploy:
        for r in v.versions:
            r.live = False
        rec.live = True
    v.versions.append(rec)
    save(v)
    return rec


def rollback(v: Versions) -> VersionRecord:
    """Make the previous deployed version live again; mark the current one rolled_back."""
    cur = live(v)
    if cur is None:
        raise ValueError("no live version")
    prev = [r for r in v.versions if r.version < cur.version and r.gate_result in ("deployed", "rolled_back")]
    if not prev:
        raise ValueError("there is no earlier deployed version to roll back to")
    target = max(prev, key=lambda r: r.version)
    cur.live, cur.gate_result = False, "rolled_back"
    cur.reason += f" | rolled back at {time.strftime('%Y-%m-%d %H:%M:%S')}"
    target.live = True
    target.gate_result = "deployed"
    save(v)
    return target


def set_live(v: Versions, version: int) -> None:
    target = next(r for r in v.versions if r.version == version)
    if target.gate_result == "rejected":
        raise ValueError("a rejected version can't go live")
    for r in v.versions:
        r.live = r.version == version
    save(v)


# ---- API keys -----------------------------------------------------------------------
def _pepper() -> bytes:
    p = config.env("API_KEY_PEPPER")
    if not p:
        raise RuntimeError("API_KEY_PEPPER is not set in .env")
    return p.encode()


def hash_key(key: str) -> str:
    return hmac.new(_pepper(), key.encode(), hashlib.sha256).hexdigest()


def create_key(v: Versions, revoke_existing: bool = True, user_id: str | None = None) -> str:
    """Create a key for `user_id`, store only its hash, return the plain key once. Regenerating revokes only
    that user's earlier keys for this specialist."""
    key = f"sk_{v.specialist_id[:12]}_{secrets.token_urlsafe(24)}"
    now = time.time()
    if revoke_existing:
        for k in v.api_keys:
            if k.revoked is None and k.user_id == user_id:
                k.revoked = now
    v.api_keys.append(ApiKeyRecord(key_id=secrets.token_hex(4), hash=hash_key(key), created=now, user_id=user_id))
    save(v)
    return key


def revoke_key(v: Versions, key_id: str) -> None:
    for k in v.api_keys:
        if k.key_id == key_id and k.revoked is None:
            k.revoked = time.time()
    save(v)


def key_matches(v: Versions, key: str) -> bool:
    h = hash_key(key)
    return any(hmac.compare_digest(k.hash, h) for k in v.api_keys if k.revoked is None)


def bundle_meta(sid: str, version: int) -> dict:
    return json.loads((bundle_dir(sid, version) / "bundle.json").read_text())
