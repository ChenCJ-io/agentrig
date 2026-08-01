#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)

set -a
# shellcheck disable=SC1091
source "$ROOT_DIR/.env.local-agentteams"
# shellcheck disable=SC1091
source "$ROOT_DIR/.agentrig/local-demo/runtime.env"
set +a
export AGENTRIG_CONFIG_FILE="$ROOT_DIR/.agentrig/local-demo/agentrig.toml"

cd "$ROOT_DIR"
exec .venv/bin/agentrig serve
