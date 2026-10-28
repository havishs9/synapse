"""Phase 0: Sandboxes whoami (permissions + limits). Writes runs/verify/sandbox_whoami.json without the token id."""
import json
import os
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")
from contree_sdk import ContreeSync  # noqa: E402  (reads NEBIUS_API_KEY / NEBIUS_PROJECT_ID from env)

client = ContreeSync()
info = asdict(client.get_token_info())
info.pop("token_uuid", None)
out = Path(os.environ.get("RUNS_DIR", "./runs")) / "verify" / "sandbox_whoami.json"
out.write_text(json.dumps(info, indent=2))
print(json.dumps(info, indent=2))
