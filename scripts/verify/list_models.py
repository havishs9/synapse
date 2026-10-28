"""Phase 0: list Token Factory models (plain and verbose) and save raw responses to runs/verify/."""
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(".env")
base = os.environ["NEBIUS_BASE_URL"].rstrip("/")
headers = {"Authorization": f"Bearer {os.environ['NEBIUS_API_KEY']}"}
out_dir = Path(os.environ.get("RUNS_DIR", "./runs")) / "verify"
out_dir.mkdir(parents=True, exist_ok=True)

for name, params in [("models_list.json", {}), ("models_list_verbose.json", {"verbose": "true"})]:
    r = httpx.get(f"{base}/models", params=params, headers=headers, timeout=30)
    r.raise_for_status()
    (out_dir / name).write_text(json.dumps(r.json(), indent=2))
    print(f"{name}: {len(r.json()['data'])} models")
