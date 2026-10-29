#!/usr/bin/env bash
# Startup script of a build-worker Nebius AI Job (injected by backend/builds/dispatcher.py with --inject-file).
# Downloads the repo at SYNAPSE_REPO_TARBALL, installs dependencies, and runs one queued build (SYNAPSE_RUN_ID).
# The pre-built image (docs/TEAM_PLAN.md §2.4) will replace the install step.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive PIP_DISABLE_PIP_VERSION_CHECK=1
: "${SYNAPSE_RUN_ID:?SYNAPSE_RUN_ID is not set}"
if [ ! -f /app/backend/builds/worker.py ]; then
  apt-get update -qq && apt-get install -y -qq --no-install-recommends libgomp1 curl ca-certificates >/dev/null
  mkdir -p /app && cd /app
  curl -fsSL "${SYNAPSE_REPO_TARBALL:-https://github.com/havishs9/synapse/archive/refs/heads/main.tar.gz}" \
    | tar xz --strip-components=1
  pip install --no-cache-dir -q torch --index-url https://download.pytorch.org/whl/cpu
  pip install --no-cache-dir -q -r requirements.txt
fi
cd /app
exec python -m backend.builds.worker "$SYNAPSE_RUN_ID"
