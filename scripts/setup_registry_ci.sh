#!/usr/bin/env bash
# One-time setup, run by a human: lets GitHub Actions push the Synapse image to Nebius Container Registry, and the
# endpoint and worker jobs pull it.
#
#   bash scripts/setup_registry_ci.sh
#
# What it does (review before running):
#   1. issues a static key for the CONTAINER_REGISTRY service to the synapse-backend service account, valid 60 days
#      (docs: https://docs.nebius.com/container-registry/authentication; docker username is `iam`)
#   2. writes the token to .env as NEBIUS_REGISTRY_TOKEN (the endpoint and worker jobs pull with it)
#   3. stores the same token as the GitHub Actions secret NEBIUS_REGISTRY_TOKEN of havishs9/synapse (needs `gh` logged
#      in with admin rights on the repo)
# No secret is printed.
set -euo pipefail
cd "$(dirname "$0")/.."
N="${NEBIUS:-$(command -v nebius || echo "$HOME/.nebius/bin/nebius")}"
PROJECT=project-e04crhvwbc00syvb9v6f5s
SA=serviceaccount-e04vfj54jr4tvp1qz0
REPO=havishs9/synapse
EXPIRES=$(date -u -v+60d +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '+60 days' +%Y-%m-%dT%H:%M:%SZ)
[ -f .env ] || { echo "No .env in the repo root" >&2; exit 1; }

"$N" iam static-key issue --parent-id "$PROJECT" --name "synapse-registry-ci-$(date +%Y%m%d)" \
  --account-service-account-id "$SA" --service CONTAINER_REGISTRY --expires-at "$EXPIRES" --format json \
| python3 -c '
import json, re, subprocess, sys
from pathlib import Path
d = json.load(sys.stdin)
tok = d.get("token") or (d.get("status") or {}).get("token") or ""
if not tok:
    sys.exit("no token in the CLI output (fields: %s)" % ", ".join(d))
p = Path(".env"); t = p.read_text(); line = "NEBIUS_REGISTRY_TOKEN=" + tok
t, n = re.subn(r"^NEBIUS_REGISTRY_TOKEN=.*$", line, t, flags=re.M)
p.write_text(t if n else t.rstrip("\n") + "\n" + line + "\n")
print("wrote NEBIUS_REGISTRY_TOKEN to .env (expires %s)" % sys.argv[2])
r = subprocess.run(["gh", "secret", "set", "NEBIUS_REGISTRY_TOKEN", "--repo", sys.argv[1]], input=tok, text=True,
                   capture_output=True)
print("GitHub secret NEBIUS_REGISTRY_TOKEN:", "set" if r.returncode == 0 else "FAILED: " + r.stderr.strip()[:200])
' "$REPO" "$EXPIRES"
echo "next: run the 'image' workflow (gh workflow run image.yml --repo $REPO), or push to main"
