#!/usr/bin/env bash
# Create the Synapse endpoint on Nebius Serverless (CPU). Requires the nebius CLI with a logged-in profile.
# Reads secrets from .env without printing them. Endpoint auth stays off: specialists use their own API keys.
set -euo pipefail
cd "$(dirname "$0")/../.."
NAME="${1:-synapse}"
PRESET="${PRESET:-4vcpu-16gb}"
set -a; source .env; set +a
ENVS="APP_MODE=${DEPLOY_APP_MODE:-replay},TRAINING_BACKEND=local,ARTIFACTS_DIR=./artifacts/demo,RUNS_DIR=./runs"
ENVS+=",NEBIUS_BASE_URL=${NEBIUS_BASE_URL},CREDIT_BUDGET_USD=${CREDIT_BUDGET_USD:-5},DEMO_DAILY_BUDGET_USD=${DEMO_DAILY_BUDGET_USD:-3}"
ENVS+=",NEBIUS_API_KEY=${NEBIUS_API_KEY},SPECIALIST_ADMIN_TOKEN=${SPECIALIST_ADMIN_TOKEN},API_KEY_PEPPER=${API_KEY_PEPPER}"
nebius ai endpoint create \
  --name "$NAME" \
  --image python:3.12-slim \
  --inject-file "deploy/serverless/bootstrap.sh:/bootstrap.sh" \
  --container-command "bash /bootstrap.sh" \
  --container-port 8000 \
  --platform cpu-d3 \
  --preset "$PRESET" \
  --disk-size 40Gi \
  --env "$ENVS" > /dev/null
ID=$(nebius ai endpoint get-by-name --name "$NAME" --format jsonpath='{.metadata.id}')
echo "endpoint id: $ID"
nebius ai endpoint get "$ID" --format json | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print('\n'.join(u for u in d.get('status',{}).get('public_endpoints',[]) if u.startswith('https://')))"
