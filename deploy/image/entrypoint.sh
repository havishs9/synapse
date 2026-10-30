#!/usr/bin/env bash
# Container entrypoint. If the service account's credentials file was injected (NEBIUS_SA_CREDENTIALS_FILE), create a
# CLI profile from it so the dispatcher can launch worker jobs as the service account. Then run the command.
set -euo pipefail
if [ -n "${NEBIUS_SA_CREDENTIALS_FILE:-}" ] && [ -f "$NEBIUS_SA_CREDENTIALS_FILE" ]; then
  "$NEBIUS_CLI" profile create synapse-sa --endpoint api.nebius.cloud \
    --service-account-file "$NEBIUS_SA_CREDENTIALS_FILE" --parent-id "${NEBIUS_PROJECT_ID}" >/dev/null 2>&1 \
    || echo "[entrypoint] couldn't create the service-account CLI profile; worker jobs won't start" >&2
  export NEBIUS_CLI_PROFILE=synapse-sa
fi
exec "$@"
