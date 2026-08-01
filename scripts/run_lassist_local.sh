#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
LASSIST_DIR=${LASSIST_DIR:-"/Users/chenchunjie/Desktop/Project/lassist-v1-develop"}

set -a
# shellcheck disable=SC1091
source "$ROOT_DIR/.env.local-agentteams"
set +a

cd "$LASSIST_DIR"
exec .venv/bin/python start_server.py --port 8000
