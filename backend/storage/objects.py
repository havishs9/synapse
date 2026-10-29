"""Nebius Object Storage (S3 API) for files: specialist version bundles and run folders.

Layout in the bucket (docs/TEAM_PLAN.md §2.2), owner = Supabase user id, or `public` for demo / no-login:
  users/<owner>/specialists/<specialist_id>/v<n>/{bundle.json, model.joblib}
  users/<owner>/runs/<run_id>/...            (run folder without candidate model files)
Used when OBJECT_STORAGE_ACCESS_KEY is set; OBJECT_STORAGE_BACKEND=off disables it (tests), and
OBJECT_STORAGE_BACKEND=local:<dir> uses a local folder with the same layout (tests).
Loading a model file (joblib) runs code, so bundles are only loaded when every file's SHA-256 matches the hash
the pipeline recorded in Postgres when it wrote the version (`verify_files`).
"""
from __future__ import annotations

import hashlib
import shutil
import threading
from pathlib import Path

from backend import config

_client = None
_lock = threading.Lock()
# A run folder is uploaded without these (candidate models are hundreds of MB; the shipped model is the version
# bundle, stored on its own).
RUN_SKIP_DIRS = {"candidates", "bundle"}
RUN_KEEP_IN_SKIPPED = {"metrics.json", "error.log"}


class StorageError(RuntimeError):
    pass


def mode() -> str:
    m = config.env("OBJECT_STORAGE_BACKEND", "s3")
    if m.startswith("local:") or m == "off":
        return m
    return "s3" if config.env("OBJECT_STORAGE_ACCESS_KEY") and config.env("OBJECT_STORAGE_SECRET_KEY") else "off"


def enabled() -> bool:
    return mode() != "off"


def bucket() -> str:
    return config.env("OBJECT_STORAGE_BUCKET") or ""


def owner_prefix(user_id: str | None) -> str:
    return f"users/{user_id or 'public'}"


def specialist_prefix(user_id: str | None, sid: str, version: int) -> str:
    return f"{owner_prefix(user_id)}/specialists/{sid}/v{version}"


def run_prefix(user_id: str | None, run_id: str) -> str:
    return f"{owner_prefix(user_id)}/runs/{run_id}"


def uri(prefix: str) -> str:
    return f"s3://{bucket()}/{prefix}" if mode() == "s3" else f"{mode()}/{prefix}"


def prefix_of(artifact_uri: str) -> str | None:
    """Bucket prefix of an artifact URI written by this module (None for local-only URIs)."""
    for head in (f"s3://{bucket()}/", f"{mode()}/"):
        if artifact_uri.startswith(head):
            return artifact_uri[len(head):]
    return None


def _s3():
    global _client
    with _lock:
        if _client is None:
            import boto3
            from botocore.config import Config
            _client = boto3.client(
                "s3", endpoint_url=config.env("OBJECT_STORAGE_ENDPOINT"), region_name=config.env("OBJECT_STORAGE_REGION"),
                aws_access_key_id=config.env("OBJECT_STORAGE_ACCESS_KEY"),
                aws_secret_access_key=config.env("OBJECT_STORAGE_SECRET_KEY"),
                config=Config(s3={"addressing_style": "path"}, connect_timeout=10, read_timeout=60,
                              retries={"mode": "standard", "max_attempts": 5},
                              request_checksum_calculation="when_required",
                              response_checksum_validation="when_required"))
        return _client


def _local_root() -> Path:
    return Path(mode()[len("local:"):])


# ---- primitives -------------------------------------------------------------------------
def put_file(src: Path, key: str) -> None:
    if mode().startswith("local:"):
        dest = _local_root() / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return
    _s3().upload_file(str(src), bucket(), key)


def get_file(key: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if mode().startswith("local:"):
        src = _local_root() / key
        if not src.is_file():
            raise StorageError(f"missing object {key}")
        shutil.copy2(src, dest)
        return
    from botocore.exceptions import ClientError
    try:
        _s3().download_file(bucket(), key, str(dest))
    except ClientError as exc:
        raise StorageError(f"couldn't download {key}: {exc.response.get('Error', {}).get('Code')}") from exc


def list_keys(prefix: str) -> list[str]:
    prefix = prefix.rstrip("/") + "/"
    if mode().startswith("local:"):
        base = _local_root() / prefix
        return sorted(str(p.relative_to(_local_root())) for p in base.rglob("*") if p.is_file()) if base.exists() else []
    keys, token = [], None
    while True:
        kw = {"Bucket": bucket(), "Prefix": prefix, **({"ContinuationToken": token} if token else {})}
        page = _s3().list_objects_v2(**kw)
        keys += [o["Key"] for o in page.get("Contents", [])]
        if not page.get("IsTruncated"):
            return keys
        token = page["NextContinuationToken"]


def delete_prefix(prefix: str) -> int:
    keys = list_keys(prefix)
    if mode().startswith("local:"):
        shutil.rmtree(_local_root() / prefix, ignore_errors=True)
        return len(keys)
    for i in range(0, len(keys), 1000):
        _s3().delete_objects(Bucket=bucket(), Delete={"Objects": [{"Key": k} for k in keys[i:i + 1000]]})
    return len(keys)


# ---- hashes -------------------------------------------------------------------------------
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def file_hashes(folder: Path) -> dict[str, str]:
    return {str(p.relative_to(folder)): sha256(p) for p in sorted(folder.rglob("*")) if p.is_file()}


def verify_files(folder: Path, expected: dict[str, str], names: list[str] | None = None) -> bool:
    for name in names or list(expected):
        p = folder / name
        if name not in expected or not p.is_file() or sha256(p) != expected[name]:
            return False
    return True


# ---- folders ------------------------------------------------------------------------------
def upload_dir(folder: Path, prefix: str, include=None) -> int:
    n = 0
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(folder)
        if p.is_file() and (include is None or include(rel)):
            put_file(p, f"{prefix}/{rel.as_posix()}")
            n += 1
    return n


def download_dir(prefix: str, dest: Path, names: list[str] | None = None) -> int:
    """Download a prefix (or only `names` under it) into a fresh temp folder, then move it into place."""
    tmp = dest.with_name(dest.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    keys = [f"{prefix}/{n}" for n in names] if names is not None else list_keys(prefix)
    if not keys:
        raise StorageError(f"nothing stored under {prefix}")
    for k in keys:
        get_file(k, tmp / k[len(prefix) + 1:])
    if dest.exists():
        shutil.rmtree(dest)
    tmp.rename(dest)
    return len(keys)


def run_file_wanted(rel: Path) -> bool:
    parts = rel.parts
    if parts and parts[0] in RUN_SKIP_DIRS:
        return rel.name in RUN_KEEP_IN_SKIPPED
    return True


def upload_run(run_dir: Path, user_id: str | None) -> int:
    return upload_dir(run_dir, run_prefix(user_id, run_dir.name), include=run_file_wanted)
