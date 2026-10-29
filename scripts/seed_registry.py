"""Load the demo specialists (artifacts/demo/specialists/*/versions.json) into Postgres as public demo
specialists (no owner), with each bundle's file hashes. With Object Storage configured, also upload the bundles to
users/public/specialists/... and the recorded runs (artifacts/demo/runs) to users/public/runs/....
Idempotent: rerun after a new snapshot. Keys aren't copied (snapshots have none).
  .venv/bin/python scripts/seed_registry.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.schemas import Versions  # noqa: E402
from backend.storage import db, objects  # noqa: E402
from backend.versions import registry  # noqa: E402


def main() -> int:
    if not db.enabled():
        print("SUPABASE_DB_URL is empty (or REGISTRY_BACKEND=files)", file=sys.stderr)
        return 1
    demo = ROOT / "artifacts" / "demo"
    for p in sorted((demo / "specialists").glob("*/versions.json")):
        v = Versions.read(p)
        v.user_id, v.api_keys = None, []
        for r in v.versions:
            folder = p.parent / f"v{r.version}"
            r.artifact_files = objects.file_hashes(folder)
            if objects.enabled():
                prefix = objects.specialist_prefix(None, v.specialist_id, r.version)
                objects.upload_dir(folder, prefix)
                r.artifact_uri = objects.uri(prefix)
        registry.save(v)
        live = registry.live(v)
        print(f"{v.specialist_id}: {len(v.versions)} version(s), live v{live.version if live else '-'}"
              f"{', bundles uploaded' if objects.enabled() else ''}")
    if objects.enabled():
        for run in sorted(d for d in (demo / "runs").iterdir() if d.is_dir()):
            print(f"run {run.name}: {objects.upload_run(run, None)} files uploaded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
