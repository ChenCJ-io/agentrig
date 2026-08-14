#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
MODE=${1:-local}
PYTHON="$ROOT_DIR/.venv/bin/python"
AGENTRIG="$ROOT_DIR/.venv/bin/agentrig"

log() {
  printf '[v2.3-acceptance] %s\n' "$*"
}

require_value() {
  local name=$1
  test -n "${!name:-}" || {
    printf '[v2.3-acceptance] ERROR: %s is required for live acceptance\n' "$name" >&2
    exit 64
  }
}

free_port() {
  "$PYTHON" -c 'import socket; sock = socket.socket(); sock.bind(("127.0.0.1", 0)); print(sock.getsockname()[1]); sock.close()'
}

accept_local() {
  test -x "$PYTHON" || {
    printf '[v2.3-acceptance] ERROR: run uv sync --extra dev first\n' >&2
    exit 64
  }
  log "validating all Skill contracts"
  (cd "$ROOT_DIR" && "$PYTHON" -m scripts.validate_skill_contracts)
  log "running Python tests, Ruff, and mypy"
  (cd "$ROOT_DIR" && "$PYTHON" -m pytest -q)
  (cd "$ROOT_DIR" && "$PYTHON" -m ruff check .)
  (cd "$ROOT_DIR" && "$PYTHON" -m mypy src/agentrig)
  log "verifying an isolated SQLite migration round trip"
  local migration_root
  migration_root=$(mktemp -d)
  (
    export AGENTRIG_DATABASE__URL="sqlite+aiosqlite:///${migration_root}/agentrig.db"
    cd "$ROOT_DIR"
    "$AGENTRIG" db upgrade
    "$AGENTRIG" db downgrade
    "$AGENTRIG" db upgrade
    "$AGENTRIG" db current
  )
  log "running Web unit, type, build, and browser-contract tests"
  (cd "$ROOT_DIR/web" && npm test)
  (cd "$ROOT_DIR/web" && npm run typecheck)
  (cd "$ROOT_DIR/web" && npm run build)
  (cd "$ROOT_DIR/web" && npm run e2e -- assistant-workspace.spec.ts evaluation-workspace.spec.ts)
  log "running Browser -> FastAPI -> SQLite -> Reference Target acceptance"
  local browser_root target_port server_port
  browser_root=$(mktemp -d)
  target_port=$(free_port)
  server_port=$(free_port)
  while test "$server_port" = "$target_port"; do
    server_port=$(free_port)
  done
  (
    export AGENTRIG_REFERENCE_STATE_DIR="$browser_root/reference-services"
    export AGENTRIG_REFERENCE_TARGET_PORT="$target_port"
    export AGENTRIG_REFERENCE_SERVER_PORT="$server_port"
    export AGENTRIG_REFERENCE_SKIP_INSTALL=1
    export AGENTRIG_REFERENCE_SKIP_WEB_VERIFY=1
    export AGENTRIG_E2E_REAL_BACKEND=1
    export AGENTRIG_WEB_API_TARGET="http://127.0.0.1:${server_port}"
    cleanup_reference_services() {
      (cd "$ROOT_DIR" && scripts/reference_demo.sh down) || true
    }
    trap cleanup_reference_services EXIT
    (cd "$ROOT_DIR" && scripts/reference_demo.sh setup --profile reference-ci)
    (cd "$ROOT_DIR/web" && CI=1 npm run e2e -- real-backend.spec.ts)
  )
  log "local deterministic acceptance passed"
}

accept_live() {
  require_value AGENTRIG_TEST_POSTGRES_URL
  require_value AGENTRIG_TEST_AGENTSCOPE_AGUI_URL
  require_value AGENTRIG_AGENTTEAMS_V112_OBSERVATION
  require_value AGENTRIG_AGENTTEAMS_V122_OBSERVATION
  local output_root
  output_root=${AGENTRIG_V23_ACCEPTANCE_OUTPUT_DIR:-"$ROOT_DIR/.agentrig/v23-live"}
  mkdir -p "$output_root"
  log "running PostgreSQL multi-worker and retention acceptance"
  (
    export AGENTRIG_DATABASE__URL="$AGENTRIG_TEST_POSTGRES_URL"
    cd "$ROOT_DIR"
    "$PYTHON" -m pytest -q tests/v1/test_postgresql.py
  )
  log "collecting AgentScope live compatibility evidence"
  local agentscope_args=(
    --endpoint "$AGENTRIG_TEST_AGENTSCOPE_AGUI_URL"
    --expected-version "${AGENTRIG_TEST_AGENTSCOPE_VERSION:-2.0.6}"
    --run-path "${AGENTRIG_TEST_AGENTSCOPE_RUN_PATH:-/agui}"
    --health-path "${AGENTRIG_TEST_AGENTSCOPE_HEALTH_PATH:-/health}"
    --capability-path "${AGENTRIG_TEST_AGENTSCOPE_CAPABILITY_PATH:-/capabilities}"
    --output "$output_root/agentscope-v2.0.6.json"
  )
  if test -n "${AGENTRIG_TEST_AGENTSCOPE_SECRET_REF:-}"; then
    agentscope_args+=(--secret-ref "$AGENTRIG_TEST_AGENTSCOPE_SECRET_REF")
  fi
  (cd "$ROOT_DIR" && "$PYTHON" -m scripts.run_agentscope_live_acceptance "${agentscope_args[@]}")
  log "building isolated AgentTeams compatibility reports"
  "$AGENTRIG" agentteams-compat \
    --manifest "$ROOT_DIR/deploy/agentteams/profiles/v1.1.2-competition/manifest.json" \
    --observation "$AGENTRIG_AGENTTEAMS_V112_OBSERVATION" \
    --output "$output_root/agentteams-v1.1.2.json"
  "$AGENTRIG" agentteams-compat \
    --manifest "$ROOT_DIR/deploy/agentteams/profiles/v1.2.2-current/manifest.json" \
    --observation "$AGENTRIG_AGENTTEAMS_V122_OBSERVATION" \
    --output "$output_root/agentteams-v1.2.2.json"
  log "live acceptance passed; reports: $output_root"
}

case "$MODE" in
  local) accept_local ;;
  live) accept_live ;;
  all) accept_local; accept_live ;;
  *)
    printf 'Usage: scripts/accept_v23.sh local|live|all\n' >&2
    exit 64
    ;;
esac
