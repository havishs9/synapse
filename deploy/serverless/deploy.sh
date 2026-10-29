#!/usr/bin/env bash
# Create the Synapse endpoint on Nebius Serverless (CPU) from the pre-built image (Dockerfile, pushed to Nebius
# Container Registry by .github/workflows/image.yml). Requires the nebius CLI with a logged-in profile.
# Reads secrets from .env without printing them. Endpoint auth stays off: specialists use their own API keys.
# Platform, preset and disk come from config/pricing.yaml, so cost numbers match the deployed endpoint.
#   ./deploy/serverless/deploy.sh [name]          create the endpoint
#   DRY_RUN=1 ./deploy/serverless/deploy.sh       validate the request without creating anything
#   SYNAPSE_IMAGE=<ref> ...                       another image (default: $NEBIUS_REGISTRY/synapse:main)
# Container settings can't change after creation; for a new image under the same tag, `nebius ai endpoint restart`.
set -euo pipefail
cd "$(dirname "$0")/../.."
NAME="${1:-synapse}"
NEBIUS="${NEBIUS:-$(command -v nebius || echo "$HOME/.nebius/bin/nebius")}"
PY="${PY:-.venv/bin/python}"
[ -f .env ] || { echo "No .env in the repo root; copy it from a teammate first." >&2; exit 1; }
set -a; source .env; set +a
for v in NEBIUS_API_KEY NEBIUS_BASE_URL SPECIALIST_ADMIN_TOKEN API_KEY_PEPPER NEBIUS_REGISTRY NEBIUS_REGISTRY_TOKEN; do
  [ -n "${!v:-}" ] || { echo "$v is empty in .env" >&2; exit 1; }
done
IMAGE="${SYNAPSE_IMAGE:-$NEBIUS_REGISTRY/synapse:main}"
read -r PLATFORM PRESET DISK < <("$PY" -c "from backend import config; s = config.pricing()['serverless_cpu']; \
print(s['platform'], s['chosen_preset'], s['disk_gib'])")

# One --env flag per variable: the CLI takes KEY=VALUE pairs as a repeatable flag, not a comma list.
ENVS=(
  "APP_MODE=${DEPLOY_APP_MODE:-live}" "TRAINING_BACKEND=${DEPLOY_TRAINING_BACKEND:-jobs}" "WORKER_IMAGE=$IMAGE"
  "ARTIFACTS_DIR=./artifacts/demo" "RUNS_DIR=./artifacts/demo/runs" "NEBIUS_BASE_URL=${NEBIUS_BASE_URL}"
  "NEBIUS_API_KEY=${NEBIUS_API_KEY}" "SPECIALIST_ADMIN_TOKEN=${SPECIALIST_ADMIN_TOKEN}" "API_KEY_PEPPER=${API_KEY_PEPPER}"
  "NEBIUS_REGISTRY=${NEBIUS_REGISTRY}" "NEBIUS_REGISTRY_TOKEN=${NEBIUS_REGISTRY_TOKEN}"
)
# Records (Supabase), sign-in, the frontend's origin, files (Object Storage), budgets and caps, when set in .env.
for v in NEBIUS_PROJECT_ID HF_TOKEN TAVILY_API_KEY SUPABASE_URL SUPABASE_DB_URL SUPABASE_JWT_SECRET AUTH_REQUIRED \
         CORS_ORIGINS OBJECT_STORAGE_ENDPOINT OBJECT_STORAGE_REGION OBJECT_STORAGE_BUCKET OBJECT_STORAGE_ACCESS_KEY \
         OBJECT_STORAGE_SECRET_KEY CREDIT_BUDGET_USD DEMO_DAILY_BUDGET_USD USER_DAILY_BUILD_BUDGET_USD \
         GLOBAL_DAILY_BUILD_BUDGET_USD TOKEN_FACTORY_TOTAL_BUDGET_USD MAX_CONCURRENT_BUILDS \
         MAX_CONCURRENT_BUILDS_PER_USER MAX_BUILDS_PER_USER_PER_DAY WORKER_TOTAL_BUDGET_USD \
         TAVILY_MAX_SEARCHES_PER_BUILD TAVILY_DAILY_SEARCH_LIMIT MAX_REPAIR_ROUNDS DEMO_MONTHLY_VOLUME SANDBOX_BASE_URL; do
  [ -n "${!v:-}" ] && ENVS+=("$v=${!v}")
done
ENV_FLAGS=()
for e in "${ENVS[@]}"; do ENV_FLAGS+=(--env "$e"); done
# The service account's credentials let the dispatcher launch worker jobs as that account (deploy/image/entrypoint.sh).
INJECT=()
if [ -n "${NEBIUS_SA_CREDENTIALS_FILE:-}" ] && [ -f "$NEBIUS_SA_CREDENTIALS_FILE" ]; then
  INJECT=(--inject-file "$NEBIUS_SA_CREDENTIALS_FILE:/secrets/nebius-sa.json" --env "NEBIUS_SA_CREDENTIALS_FILE=/secrets/nebius-sa.json")
else
  echo "warning: NEBIUS_SA_CREDENTIALS_FILE not found; the endpoint can't start worker jobs" >&2
fi

echo "creating endpoint '$NAME' from $IMAGE on $PLATFORM / $PRESET with ${DISK} GiB disk${DRY_RUN:+ (dry run)}"
"$NEBIUS" ai endpoint create \
  --name "$NAME" \
  --image "$IMAGE" \
  --registry-username iam --registry-password "$NEBIUS_REGISTRY_TOKEN" \
  --container-port 8000 \
  --platform "$PLATFORM" \
  --preset "$PRESET" \
  --disk-size "${DISK}Gi" \
  --auth none \
  ${DRY_RUN:+--dry-run} \
  "${INJECT[@]}" "${ENV_FLAGS[@]}" > /dev/null
[ -n "${DRY_RUN:-}" ] && { echo "dry run passed"; exit 0; }

# Print the managed https:// URL(s) without echoing the spec (it contains the env values).
"$NEBIUS" ai endpoint get-by-name --name "$NAME" --format json | "$PY" -c '
import json, re, sys
d = json.load(sys.stdin)
print("endpoint id:", d.get("metadata", {}).get("id"))
urls = sorted(set(re.findall(r"https://[^\s\"]+", json.dumps(d.get("status", {})))))
print("\n".join(urls) or "no https URL yet; rerun: nebius ai endpoint get-by-name --name '"$NAME"' --format json")'
echo "then check GET <url>/health"
