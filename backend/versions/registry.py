"""Specialist registry: versions.json per specialist, artifact bundles, API keys (hashed), live version.

Layout under ARTIFACTS_DIR:
  specialists/<specialist_id>/versions.json
  specialists/<specialist_id>/v<n>/{model.joblib, bundle.json}
  synapse.sqlite  (list of runs, specialists, versions; for the sidebar)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import shutil
import sqlite3
import time
from pathlib import Path

from backend import config
from backend.schemas import ApiKeyRecord, TaskCard, VersionRecord, Versions

# 8 accessible hues for specialist identity (DESIGN.md); the main model stays neutral.
PALETTE = ["#2F6FDE", "#0E8F6E", "#C2410C", "#7C3AED", "#B4235A", "#0F766E", "#A16207", "#4338CA"]


def root() -> Path:
    d = config.artifacts_dir() / "specialists"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db() -> sqlite3.Connection:
    config.artifacts_dir().mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.artifacts_dir() / "synapse.sqlite")
    c.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, task_id TEXT, kind TEXT, status TEXT, "
              "created REAL, specialist_id TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS specialists (specialist_id TEXT PRIMARY KEY, display_name TEXT, "
              "task_id TEXT, color TEXT, monogram TEXT, created REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS versions (specialist_id TEXT, version INTEGER, run_id TEXT, "
              "gate_result TEXT, live INTEGER, created REAL, PRIMARY KEY (specialist_id, version))")
    return c


def record_run(run_id: str, task_id: str, kind: str, status: str, specialist_id: str | None = None) -> None:
    with db() as c:
        c.execute("INSERT INTO runs VALUES (?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET status=excluded.status, "
                  "specialist_id=COALESCE(excluded.specialist_id, runs.specialist_id)",
                  (run_id, task_id, kind, status, time.time(), specialist_id))


def list_runs() -> list[dict]:
    with db() as c:
        rows = c.execute("SELECT run_id, task_id, kind, status, created, specialist_id FROM runs ORDER BY created DESC")
        return [dict(zip(("run_id", "task_id", "kind", "status", "created", "specialist_id"), r)) for r in rows]


def monogram(name: str) -> str:
    words = re.findall(r"[A-Za-z]+", name)
    return (words[0][0] + (words[1][0] if len(words) > 1 else words[0][1])).upper() if words else "SP"


def path(sid: str) -> Path:
    return root() / sid / "versions.json"


def load(sid: str) -> Versions:
    return Versions.read(path(sid))


def save(v: Versions) -> None:
    v.write(path(v.specialist_id))
    with db() as c:
        c.execute("INSERT OR REPLACE INTO specialists VALUES (?,?,?,?,?,COALESCE((SELECT created FROM specialists "
                  "WHERE specialist_id=?), ?))", (v.specialist_id, v.display_name, v.task_id, v.color, v.monogram,
                                                   v.specialist_id, time.time()))
        for r in v.versions:
            c.execute("INSERT OR REPLACE INTO versions VALUES (?,?,?,?,?,?)",
                      (v.specialist_id, r.version, r.run_id, r.gate_result, int(r.live), r.created))


def list_specialists() -> list[Versions]:
    return [Versions.read(p) for p in sorted(root().glob("*/versions.json"))]


def get_or_create(card: TaskCard) -> Versions:
    sid = re.sub(r"[^a-z0-9]+", "-", card.task_name.lower()).strip("-")
    if path(sid).exists():
        return load(sid)
    used = {s.color for s in list_specialists()}
    color = next((c for c in PALETTE if c not in used), PALETTE[len(used) % len(PALETTE)])
    v = Versions(specialist_id=sid, display_name=card.task_name, monogram=monogram(card.task_name), color=color,
                 task_id=card.task_id, api_route=f"/v1/specialists/{sid}/predict")
    save(v)
    return v


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


def create_key(v: Versions, revoke_existing: bool = True) -> str:
    """Create a key, store only its hash, return the plain key once."""
    key = f"sk_{v.specialist_id[:12]}_{secrets.token_urlsafe(24)}"
    now = time.time()
    if revoke_existing:
        for k in v.api_keys:
            if k.revoked is None:
                k.revoked = now
    v.api_keys.append(ApiKeyRecord(key_id=secrets.token_hex(4), hash=hash_key(key), created=now))
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
    return json.loads((root() / sid / f"v{version}" / "bundle.json").read_text())
