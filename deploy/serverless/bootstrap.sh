#!/usr/bin/env bash
# Startup script for the Nebius Serverless CPU endpoint (injected with --inject-file; no custom image needed).
# Downloads this public repo, installs dependencies, and serves the app + shared specialist server on :8000.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive PIP_DISABLE_PIP_VERSION_CHECK=1
apt-get update -qq && apt-get install -y -qq --no-install-recommends libgomp1 curl ca-certificates >/dev/null
mkdir -p /app && cd /app
curl -fsSL "${SYNAPSE_REPO_TARBALL:-https://github.com/havishs9/synapse/archive/refs/heads/main.tar.gz}" \
  | tar xz --strip-components=1
pip install --no-cache-dir -q torch --index-url https://download.pytorch.org/whl/cpu
pip install --no-cache-dir -q -r requirements.txt
if [ "${SYNAPSE_LIVE_BUILDS:-0}" = "1" ]; then python scripts/demo_data.py || echo "demo data download failed; replay only"; fi
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --proxy-headers
