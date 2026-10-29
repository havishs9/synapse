#!/usr/bin/env bash
# Create the Synapse endpoint on Nebius Serverless (CPU). Requires the nebius CLI with a logged-in profile.
# Reads secrets from .env without printing them. Endpoint auth stays off: specialists use their own API keys.
# Platform, preset and disk come from config/pricing.yaml, so cost numbers match the deployed endpoint.
#   ./deploy/serverless/deploy.sh [name]          create the endpoint
#   DRY_RUN=1 ./deploy/serverless/deploy.sh       validate the request without creating anything
set -euo pipefail
cd "$(dirname "$0")/../.."
NAME="${1:-synapse}"
NEBIUS="${NEBIUS:-$(command -v nebius || echo "$HOME/.nebius/bin/nebius")}"
PY="${PY:-.venv/bin/python}"
[ -f .env ] || { echo "No .env in the repo root; copy it from a teammate first." >&2; exit 1; }
set -a; source .env; set +a
for v in NEBIUS_API_KEY NEBIUS_BASE_URL SPECIALIST_ADMIN_TOKEN API_KEY_PEPPER; do
  [ -n "${!v:-}" ] || { echo "$v is empty in .env" >&2; exit 1; }
done
read -r PLATFORM PRESET DISK < <("$PY" -c "from backend import config; s = config.pricing()['serverless_cpu']; \
print(s['platform'], s['chosen_preset'], s['disk_gib'])")

# One --env flag per variable: the CLI takes KEY=VALUE pairs as a repeatable flag, not a comma list.
ENVS=(
  "APP_MODE=${DEPLOY_APP_MODE:-replay}" "TRAINING_BACKEND=local" "ARTIFACTS_DIR=./artifacts/demo" "RUNS_DIR=./artifacts/demo/runs"
  "NEBIUS_BASE_URL=${NEBIUS_BASE_URL}" "CREDIT_BUDGET_USD=${CREDIT_BUDGET_USD:-5}"
  "DEMO_DAILY_BUDGET_USD=${DEMO_DAILY_BUDGET_USD:-3}"
  "NEBIUS_API_KEY=${NEBIUS_API_KEY}" "SPECIALIST_ADMIN_TOKEN=${SPECIALIST_ADMIN_TOKEN}" "API_KEY_PEPPER=${API_KEY_PEPPER}"
)
# Optional: records in Supabase (keys survive restarts), sign-in checks, the frontend's origin, and Object
# Storage (model bundles and run folders are fetched from the bucket on first use).
for v in SUPABASE_URL SUPABASE_DB_URL SUPABASE_JWT_SECRET AUTH_REQUIRED CORS_ORIGINS OBJECT_STORAGE_ENDPOINT \
         OBJECT_STORAGE_REGION OBJECT_STORAGE_BUCKET OBJECT_STORAGE_ACCESS_KEY OBJECT_STORAGE_SECRET_KEY; do
  [ -n "${!v:-}" ] && ENVS+=("$v=${!v}")
done
ENV_FLAGS=()
for e in "${ENVS[@]}"; do ENV_FLAGS+=(--env "$e"); done

echo "creating endpoint '$NAME' on $PLATFORM / $PRESET with ${DISK} GiB disk${DRY_RUN:+ (dry run)}"
"$NEBIUS" ai endpoint create \
  --name "$NAME" \
  --image python:3.12-slim \
  --inject-file "deploy/serverless/bootstrap.sh:/bootstrap.sh" \
  --container-command "bash /bootstrap.sh" \
  --container-port 8000 \
  --platform "$PLATFORM" \
  --preset "$PRESET" \
  --disk-size "${DISK}Gi" \
  --auth none \
  ${DRY_RUN:+--dry-run} \
  "${ENV_FLAGS[@]}" > /dev/null
[ -n "${DRY_RUN:-}" ] && { echo "dry run passed"; exit 0; }

# Print the managed https:// URL(s) without echoing the spec (it contains the env values).
"$NEBIUS" ai endpoint get-by-name --name "$NAME" --format json | "$PY" -c '
import json, re, sys
d = json.load(sys.stdin)
print("endpoint id:", d.get("metadata", {}).get("id"))
urls = sorted(set(re.findall(r"https://[^\s\"]+", json.dumps(d.get("status", {})))))
print("\n".join(urls) or "no https URL yet; rerun: nebius ai endpoint get-by-name --name '"$NAME"' --format json")'
echo "startup installs dependencies (several minutes); then check GET <url>/health"
