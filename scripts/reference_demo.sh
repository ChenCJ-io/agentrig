#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
STATE_DIR=${AGENTRIG_REFERENCE_STATE_DIR:-"$ROOT_DIR/.agentrig/reference-demo"}
LOG_DIR="$STATE_DIR/logs"
EVIDENCE_DIR="$STATE_DIR/evidence"
CONFIG_FILE="$STATE_DIR/agentrig.toml"
DATABASE_FILE="$STATE_DIR/agentrig.db"
RUN_MANIFEST="$STATE_DIR/latest-runs.json"
TARGET_PID_FILE="$STATE_DIR/reference-target.pid"
AGENTRIG_PID_FILE="$STATE_DIR/agentrig.pid"
TARGET_PORT=${AGENTRIG_REFERENCE_TARGET_PORT:-8091}
AGENTRIG_PORT=${AGENTRIG_REFERENCE_SERVER_PORT:-8020}
TARGET_URL="http://127.0.0.1:$TARGET_PORT"
AGENTRIG_URL="http://127.0.0.1:$AGENTRIG_PORT"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON="$VENV_DIR/bin/python"
TARGET_PATTERN="examples.reference_target.app:app"
AGENTRIG_PATTERN="agentrig serve"
PROFILE="reference-ci"
SCENARIO="all"
SKIP_INSTALL=${AGENTRIG_REFERENCE_SKIP_INSTALL:-0}
SKIP_WEB_VERIFY=${AGENTRIG_REFERENCE_SKIP_WEB_VERIFY:-0}
STARTED_TARGET=0
STARTED_AGENTRIG=0

log() {
  printf '[reference-demo] %s\n' "$*"
}

die() {
  printf '[reference-demo] ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

prepare_directories() {
  mkdir -p "$STATE_DIR" "$LOG_DIR" "$EVIDENCE_DIR"
}

pid_is_alive() {
  local process_id=$1
  local process_state
  kill -0 "$process_id" 2>/dev/null || return 1
  process_state=$(ps -p "$process_id" -o stat= 2>/dev/null || true)
  case "$process_state" in
    Z*|"") return 1 ;;
    *) return 0 ;;
  esac
}

pid_is_owned() {
  local process_id=$1
  local expected_pattern=$2
  local process_command
  pid_is_alive "$process_id" || return 1
  process_command=$(ps -p "$process_id" -o command= 2>/dev/null || true)
  case "$process_command" in
    *"$expected_pattern"*) return 0 ;;
    *) return 1 ;;
  esac
}

read_owned_pid() {
  local pid_file=$1
  local expected_pattern=$2
  local process_id
  test -f "$pid_file" || return 1
  process_id=$(tr -cd '0-9' < "$pid_file")
  test -n "$process_id" || return 1
  pid_is_owned "$process_id" "$expected_pattern" || return 1
  printf '%s' "$process_id"
}

wait_http() {
  local check_url=$1
  local label=$2
  local attempt
  for attempt in $(seq 1 120); do
    if curl --fail --silent --show-error "$check_url" >/dev/null 2>&1; then
      log "$label is ready"
      return 0
    fi
    sleep 0.25
  done
  die "$label did not become ready: $check_url"
}

target_is_ready() {
  curl --fail --silent "$TARGET_URL/" 2>/dev/null \
    | grep -q 'AgentRig Public Reference Target'
}

agentrig_is_ready() {
  curl --fail --silent "$AGENTRIG_URL/api/driver-types" >/dev/null 2>&1
}

install_dependencies() {
  require_command uv
  require_command curl
  require_command nohup
  require_command ps
  if test "$SKIP_INSTALL" = 1; then
    test -x "$PYTHON" || die "test mode requires an existing .venv"
    test -x "$VENV_DIR/bin/agentrig" || die "agentrig executable is missing"
    test -x "$VENV_DIR/bin/uvicorn" || die "uvicorn executable is missing"
    log "using the existing environment (test-only skip enabled)"
    return
  fi

  require_command node
  require_command npm
  log "installing locked Python dependencies"
  (cd "$ROOT_DIR" && uv sync --frozen --extra dev)
  log "installing and building the Web UI"
  (cd "$ROOT_DIR/web" && npm ci && npm run build)
}

write_runtime_config() {
  (cd "$ROOT_DIR" && "$PYTHON" -m scripts.reference_demo config \
    --path "$CONFIG_FILE" \
    --database-path "$DATABASE_FILE" \
    --host 127.0.0.1 \
    --port "$AGENTRIG_PORT" >/dev/null)
}

upgrade_database() {
  log "upgrading the reference-demo database"
  AGENTRIG_CONFIG_FILE="$CONFIG_FILE" \
    "$VENV_DIR/bin/agentrig" db upgrade
}

start_target() {
  local process_id
  if process_id=$(read_owned_pid "$TARGET_PID_FILE" "$TARGET_PATTERN"); then
    target_is_ready || die "owned Reference Target process is unhealthy (PID $process_id)"
    log "Reference Target is already running (PID $process_id)"
    return
  fi
  if target_is_ready; then
    die "port $TARGET_PORT already serves a Reference Target not owned by this state"
  fi

  rm -f "$TARGET_PID_FILE"
  log "starting Public Reference Target on $TARGET_URL"
  (
    cd "$ROOT_DIR"
    nohup "$VENV_DIR/bin/uvicorn" examples.reference_target.app:app \
      --host 127.0.0.1 \
      --port "$TARGET_PORT" \
      --workers 1 \
      --log-level info \
      >> "$LOG_DIR/reference-target.log" 2>&1 </dev/null &
    printf '%s\n' "$!" > "$TARGET_PID_FILE"
  )
  process_id=$(tr -cd '0-9' < "$TARGET_PID_FILE")
  STARTED_TARGET=1
  wait_http "$TARGET_URL/healthz" "Reference Target"
  target_is_ready || die "Reference Target identity check failed"
}

start_agentrig() {
  local process_id
  if process_id=$(read_owned_pid "$AGENTRIG_PID_FILE" "$AGENTRIG_PATTERN"); then
    agentrig_is_ready || die "owned AgentRig process is unhealthy (PID $process_id)"
    log "AgentRig is already running (PID $process_id)"
    return
  fi
  if agentrig_is_ready; then
    die "port $AGENTRIG_PORT already serves an AgentRig process not owned by this state"
  fi

  rm -f "$AGENTRIG_PID_FILE"
  log "starting AgentRig on $AGENTRIG_URL"
  (
    cd "$ROOT_DIR"
    nohup env AGENTRIG_CONFIG_FILE="$CONFIG_FILE" \
      "$VENV_DIR/bin/agentrig" serve \
      --host 127.0.0.1 \
      --port "$AGENTRIG_PORT" \
      >> "$LOG_DIR/agentrig.log" 2>&1 </dev/null &
    printf '%s\n' "$!" > "$AGENTRIG_PID_FILE"
  )
  process_id=$(tr -cd '0-9' < "$AGENTRIG_PID_FILE")
  STARTED_AGENTRIG=1
  wait_http "$AGENTRIG_URL/api/driver-types" "AgentRig"
}

stop_owned_process() {
  local pid_file=$1
  local expected_pattern=$2
  local label=$3
  local process_id attempt
  if test ! -f "$pid_file"; then
    return
  fi
  process_id=$(tr -cd '0-9' < "$pid_file")
  if test -z "$process_id" || ! pid_is_alive "$process_id"; then
    rm -f "$pid_file"
    return
  fi
  pid_is_owned "$process_id" "$expected_pattern" \
    || die "refusing to stop unrecognized PID $process_id from $pid_file"

  kill -TERM "$process_id"
  for attempt in $(seq 1 80); do
    if ! pid_is_alive "$process_id"; then
      wait "$process_id" 2>/dev/null || true
      rm -f "$pid_file"
      log "$label stopped"
      return
    fi
    sleep 0.25
  done
  log "$label did not drain in 20s; forcing the validated PID to stop"
  kill -KILL "$process_id"
  wait "$process_id" 2>/dev/null || true
  rm -f "$pid_file"
}

cleanup_failed_setup() {
  local exit_code=$?
  if test "$exit_code" -ne 0; then
    if test "$STARTED_AGENTRIG" = 1; then
      stop_owned_process "$AGENTRIG_PID_FILE" "$AGENTRIG_PATTERN" "AgentRig"
    fi
    if test "$STARTED_TARGET" = 1; then
      stop_owned_process "$TARGET_PID_FILE" "$TARGET_PATTERN" "Reference Target"
    fi
  fi
  return "$exit_code"
}

run_helper() {
  test -x "$PYTHON" || die "run setup first; Python environment is missing"
  (cd "$ROOT_DIR" && "$PYTHON" -m scripts.reference_demo "$@")
}

seed_demo() {
  log "seeding canonical Target, Profile, and approved TestCases"
  run_helper seed --base-url "$AGENTRIG_URL" --target-url "$TARGET_URL"
}

setup_demo() {
  prepare_directories
  trap cleanup_failed_setup EXIT
  install_dependencies
  write_runtime_config
  upgrade_database
  start_target
  start_agentrig
  seed_demo
  trap - EXIT
  log "setup complete; next: scripts/reference_demo.sh verify"
}

verify_demo() {
  prepare_directories
  if test "$SKIP_WEB_VERIFY" = 1; then
    run_helper verify \
      --base-url "$AGENTRIG_URL" \
      --target-url "$TARGET_URL" \
      --skip-web
  else
    run_helper verify \
      --base-url "$AGENTRIG_URL" \
      --target-url "$TARGET_URL"
  fi
  log "verification passed: services, assets, capabilities, and Web contract"
}

run_demo() {
  prepare_directories
  log "running deterministic scenario selection: $SCENARIO"
  run_helper run \
    --base-url "$AGENTRIG_URL" \
    --target-url "$TARGET_URL" \
    --scenario "$SCENARIO" \
    --manifest "$RUN_MANIFEST"
  log "verified run manifest: $RUN_MANIFEST"
}

export_demo_evidence() {
  prepare_directories
  test -f "$RUN_MANIFEST" || die "run scenarios before exporting evidence"
  log "exporting compact, secret-free reference evidence"
  run_helper evidence \
    --base-url "$AGENTRIG_URL" \
    --target-url "$TARGET_URL" \
    --manifest "$RUN_MANIFEST" \
    --output-root "$EVIDENCE_DIR" \
    --repository-root "$ROOT_DIR"
  log "evidence export complete; pointer: $STATE_DIR/latest-evidence.json"
}

down_demo() {
  stop_owned_process "$AGENTRIG_PID_FILE" "$AGENTRIG_PATTERN" "AgentRig"
  stop_owned_process "$TARGET_PID_FILE" "$TARGET_PATTERN" "Reference Target"
  log "services stopped; database, logs, Run manifest, and evidence were preserved"
}

show_status() {
  printf 'Reference Target: '
  target_is_ready && printf 'ready (%s)\n' "$TARGET_URL" || printf 'unavailable\n'
  printf 'AgentRig: '
  agentrig_is_ready && printf 'ready (%s)\n' "$AGENTRIG_URL" || printf 'unavailable\n'
  printf 'State: %s\n' "$STATE_DIR"
  if test -f "$RUN_MANIFEST"; then
    printf 'Latest runs: %s\n' "$RUN_MANIFEST"
  fi
  if test -f "$STATE_DIR/latest-evidence.json"; then
    printf 'Latest evidence: %s\n' "$STATE_DIR/latest-evidence.json"
  fi
}

usage() {
  cat <<'EOF'
Usage: scripts/reference_demo.sh <command> [options]

Commands:
  setup       Install/build, migrate, start services, and seed canonical assets
  verify      Check HTTP health, migrations, assets, Target capabilities, and Web
  run         Run and verify the selected deterministic scenario(s)
  evidence    Export a compact JSON/Markdown evidence bundle with SHA256SUMS
  down        Stop only processes owned by this demo; preserve data and evidence
  status      Show service and artifact status
  all         Run setup, verify, all scenarios, and evidence export

Options:
  --profile reference-ci
  --scenario success|policy-regression|recovery|all

Environment overrides:
  AGENTRIG_REFERENCE_STATE_DIR
  AGENTRIG_REFERENCE_SERVER_PORT
  AGENTRIG_REFERENCE_TARGET_PORT

The reference-agentteams profile is a later full-mode slice. reference-ci is public,
deterministic, and its runtime requires no Docker, private repository, model key, or
external service.
EOF
}

command_name=${1:-status}
if test "$#" -gt 0; then
  shift
fi
while test "$#" -gt 0; do
  case "$1" in
    --profile)
      test "$#" -ge 2 || die "--profile requires a value"
      PROFILE=$2
      shift 2
      ;;
    --scenario)
      test "$#" -ge 2 || die "--scenario requires a value"
      SCENARIO=$2
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

test "$PROFILE" = "reference-ci" \
  || die "unsupported profile: $PROFILE (currently available: reference-ci)"
case "$SCENARIO" in
  success|policy-regression|recovery|all) ;;
  *) die "unsupported scenario: $SCENARIO" ;;
esac

case "$command_name" in
  setup) setup_demo ;;
  verify) verify_demo ;;
  run) run_demo ;;
  evidence) export_demo_evidence ;;
  down) down_demo ;;
  status) show_status ;;
  all) setup_demo; verify_demo; run_demo; export_demo_evidence ;;
  help) usage ;;
  *) usage; exit 2 ;;
esac
