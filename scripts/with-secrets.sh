#!/usr/bin/env bash
# Loads API keys from the secrets file into the environment, then runs the given command.
# The secrets file is sourced, never printed.
set -euo pipefail
SECRETS_FILE="${JEVTRENDS_SECRETS_FILE:-$HOME/Repos/.env.secrets}"
if [[ ! -f "$SECRETS_FILE" ]]; then
  echo "Secrets file not found: $SECRETS_FILE" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$SECRETS_FILE"
set +a
exec "$@"
