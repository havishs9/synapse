#!/usr/bin/env bash
# One-time setup, run by a human: the `synapse-backend` service account used by the API endpoint and build workers.
#
#   bash scripts/setup_service_account.sh
#
# What it does (review before running):
#   1. creates service account `synapse-backend` in the project (skipped if it exists)
#   2. adds it to the tenant's `editors` group. Nebius docs require this for Object Storage; note it gives
#      edit rights on the whole tenant, so treat its keys like an owner's password
#   3. issues an Object Storage (S3) access key, valid 60 days, and writes OBJECT_STORAGE_ACCESS_KEY /
#      OBJECT_STORAGE_SECRET_KEY into .env
#   4. generates the account's authorized key (for launching AI Jobs), valid 60 days, into
#      ~/.config/synapse/nebius-sa.json (mode 600, outside the repo) and sets NEBIUS_SA_CREDENTIALS_FILE in .env
# No secret is printed.
set -euo pipefail
cd "$(dirname "$0")/.."
N="${NEBIUS:-$(command -v nebius || echo "$HOME/.nebius/bin/nebius")}"
PROJECT=project-e04crhvwbc00syvb9v6f5s
EDITORS=group-e00p3maf515eqk67qb
CRED="$HOME/.config/synapse/nebius-sa.json"
EXPIRES=$(date -u -v+60d +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '+60 days' +%Y-%m-%dT%H:%M:%SZ)
[ -f .env ] || { echo "No .env in the repo root" >&2; exit 1; }

jget() { python3 -c "import sys,json; d=json.load(sys.stdin); print(eval('d' + sys.argv[1]))" "$1"; }

SA=$("$N" iam service-account get-by-name --parent-id "$PROJECT" --name synapse-backend --format json 2>/dev/null \
     | jget "['metadata']['id']" 2>/dev/null || true)
if [ -z "$SA" ]; then
  SA=$("$N" iam service-account create --parent-id "$PROJECT" --name synapse-backend \
       --description "Synapse API endpoint and build workers: object storage, AI jobs, registry" --format json \
       | jget "['metadata']['id']")
  echo "created service account $SA"
else
  echo "service account exists: $SA"
fi

"$N" iam group-membership create --parent-id "$EDITORS" --member-id "$SA" --format json > /dev/null 2>&1 \
  && echo "added to the editors group" || echo "editors membership: already a member (or failed; check the console)"

KEY_ID=$("$N" iam v2 access-key create --parent-id "$PROJECT" --account-service-account-id "$SA" \
         --description "synapse object storage" --expires-at "$EXPIRES" --format json | jget "['metadata']['id']")
"$N" iam v2 access-key get --id "$KEY_ID" --format json | python3 -c '
import json, re, sys
from pathlib import Path
st = json.load(sys.stdin)["status"]
vals = {"OBJECT_STORAGE_ACCESS_KEY": st["aws_access_key_id"], "OBJECT_STORAGE_SECRET_KEY": st["secret"]}
p = Path(".env"); text = p.read_text()
for k, v in vals.items():
    line = f"{k}={v}"
    text, n = re.subn(rf"^{k}=.*$", line, text, flags=re.M)
    if not n:
        text = text.rstrip("\n") + "\n" + line + "\n"
p.write_text(text)
print("wrote OBJECT_STORAGE_ACCESS_KEY and OBJECT_STORAGE_SECRET_KEY to .env (expires", sys.argv[1] + ")")
' "$EXPIRES"

mkdir -p "$(dirname "$CRED")" && chmod 700 "$(dirname "$CRED")"
"$N" iam auth-public-key generate --service-account-id "$SA" --output "$CRED" \
  --output-format service-account-json --expires-at "$EXPIRES" > /dev/null
chmod 600 "$CRED"
python3 - "$CRED" <<'EOF'
import re, sys
from pathlib import Path
p = Path(".env"); text = p.read_text(); line = f"NEBIUS_SA_CREDENTIALS_FILE={sys.argv[1]}"
text, n = re.subn(r"^NEBIUS_SA_CREDENTIALS_FILE=.*$", line, text, flags=re.M)
p.write_text(text if n else text.rstrip("\n") + "\n" + line + "\n")
print("saved the service account credentials to", sys.argv[1], "and set NEBIUS_SA_CREDENTIALS_FILE in .env")
EOF
echo "done: service account $SA"
