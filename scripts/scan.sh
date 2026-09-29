#!/usr/bin/env bash
# Runs the jevtrends CLI with API keys loaded, e.g. scripts/scan.sh scan --estimate
set -euo pipefail
exec "$(dirname "$0")/with-secrets.sh" uv run jevtrends "$@"
