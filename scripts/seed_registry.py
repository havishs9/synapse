"""Load the demo specialists (artifacts/demo/specialists/*/versions.json) into Postgres as public demo
specialists (no owner). Idempotent: rerun after a new snapshot. Keys aren't copied (snapshots have none).
  .venv/bin/python scripts/seed_registry.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.schemas import Versions  # noqa: E402
from backend.storage import db  # noqa: E402
from backend.versions import registry  # noqa: E402


def main() -> int:
    if not db.enabled():
        print("SUPABASE_DB_URL is empty (or REGISTRY_BACKEND=files)", file=sys.stderr)
        return 1
    for p in sorted((ROOT / "artifacts" / "demo" / "specialists").glob("*/versions.json")):
        v = Versions.read(p)
        v.user_id, v.api_keys = None, []
        registry.save(v)
        live = registry.live(v)
        print(f"{v.specialist_id}: {len(v.versions)} version(s), live v{live.version if live else '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
