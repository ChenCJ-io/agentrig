#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
LASSIST_DIR=${LASSIST_DIR:-}

set -a
# shellcheck disable=SC1091
source "$ROOT_DIR/.env.local-agentteams"
set +a

test -n "$LASSIST_DIR" || {
  printf 'ERROR: set LASSIST_DIR to the local lassist checkout\n' >&2
  exit 1
}
test -d "$LASSIST_DIR" || {
  printf 'ERROR: lassist directory not found: %s\n' "$LASSIST_DIR" >&2
  exit 1
}

cd "$LASSIST_DIR"
exec .venv/bin/python start_server.py --port 8000
