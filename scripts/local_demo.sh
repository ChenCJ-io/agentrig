#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
LASSIST_DIR=${LASSIST_DIR:-"/Users/chenchunjie/Desktop/Project/lassist-v1-develop"}
LOCAL_ENV="$ROOT_DIR/.env.local-agentteams"
STATE_DIR="$ROOT_DIR/.agentrig/local-demo"
RUNTIME_ENV="$STATE_DIR/runtime.env"
CONFIG_FILE="$STATE_DIR/agentrig.toml"
LOG_DIR="$STATE_DIR/logs"
INSTALLER="$ROOT_DIR/.agentrig/cache/hiclaw-install-v1.1.2.sh"
HICLAW_ENV_FILE="$STATE_DIR/hiclaw-manager.env"
HICLAW_WORKSPACE_DIR="$STATE_DIR/hiclaw-manager"
HICLAW_DATA_DIR="agentrig-hiclaw-data"
MATRIX_BASE="http://matrix-local.hiclaw.io:18080"
HIGRESS_BASE="http://127.0.0.1:18001"
HIGRESS_COOKIE="$STATE_DIR/higress.cookie"
AGENTRIG_URL="http://127.0.0.1:8010"
LASSIST_URL="http://127.0.0.1:8000"

log() {
  printf '[local-demo] %s\n' "$*"
}

die() {
  printf '[local-demo] ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

prepare_files() {
  require_command curl
  require_command docker
  require_command jq
  require_command screen
  require_command uv
  test -f "$LOCAL_ENV" || die "missing $LOCAL_ENV"
  test -f "$CONFIG_FILE" || {
    mkdir -p "$STATE_DIR"
    cp "$ROOT_DIR/deploy/agentteams/agentrig.local.toml.example" "$CONFIG_FILE"
  }
  test -d "$LASSIST_DIR" || die "lassist directory not found: $LASSIST_DIR"
  mkdir -p "$LOG_DIR" "$ROOT_DIR/.agentrig/cache"
  chmod 600 "$LOCAL_ENV" "$CONFIG_FILE"
}

load_local_env() {
  set -a
  # shellcheck disable=SC1090
  source "$LOCAL_ENV"
  if test -f "$RUNTIME_ENV"; then
    # shellcheck disable=SC1090
    source "$RUNTIME_ENV"
  fi
  set +a
  export AGENTRIG_CONFIG_FILE="$CONFIG_FILE"
}

wait_http() {
  local check_url=$1
  local label=$2
  local max_attempts=${3:-120}
  local attempt
  for attempt in $(seq 1 "$max_attempts"); do
    if curl -fsS "$check_url" >/dev/null 2>&1; then
      log "$label is ready"
      return 0
    fi
    sleep 0.5
  done
  die "$label did not become ready: $check_url"
}

ensure_docker() {
  if docker info >/dev/null 2>&1; then
    return
  fi
  log "starting Docker Desktop"
  open -a Docker
  local attempt
  for attempt in $(seq 1 180); do
    if docker info >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  die "Docker Desktop is unavailable. Approve its macOS privileged-helper prompt, then rerun."
}

stop_competing_compose() {
  local container_names
  container_names=$(docker ps \
    --filter label=com.docker.compose.project=docker-compose \
    --format '{{.Names}}' || true)
  if test -n "$container_names"; then
    log "stopping the unrelated coze-loop compose containers to free Docker resources"
    while IFS= read -r container_name; do
      test -n "$container_name" && docker stop "$container_name" >/dev/null
    done <<< "$container_names"
  fi
}

download_installer() {
  if test ! -x "$INSTALLER"; then
    curl -fsSL https://higress.ai/hiclaw/install.sh -o "$INSTALLER"
    chmod 700 "$INSTALLER"
  fi
}

install_agentteams() {
  if docker ps -a --format '{{.Names}}' | grep -qx hiclaw-controller; then
    docker start hiclaw-controller >/dev/null 2>&1 || true
    return
  fi
  stop_competing_compose
  download_installer
  log "installing pinned AgentTeams/HiClaw v1.1.2 (log: $LOG_DIR/hiclaw-install.log)"
  export HICLAW_ENV_FILE HICLAW_DATA_DIR HICLAW_WORKSPACE_DIR
  export HICLAW_NON_INTERACTIVE=1
  bash "$INSTALLER" manager > "$LOG_DIR/hiclaw-install.log" 2>&1 || {
    tail -80 "$LOG_DIR/hiclaw-install.log" | sed -E \
      's/(sk-[A-Za-z0-9_-]+)/<redacted>/g; s/(password|token|api.?key)([=: ]+)[^ ]+/\1\2<redacted>/Ig'
    die "AgentTeams installer failed"
  }
}

wait_agentteams() {
  local attempt
  for attempt in $(seq 1 180); do
    if docker exec hiclaw-controller hiclaw get managers default -o json \
      2>/dev/null | jq -e '.phase == "Running"' >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  die "AgentTeams Manager did not reach Running"
}

apply_resources() {
  log "building and applying AgentRig Manager/Curator/Judge packages"
  (cd "$ROOT_DIR" && uv run python scripts/build_agentteams_packages.py >/dev/null)
  docker exec hiclaw-controller mkdir -p /tmp/import
  docker cp "$ROOT_DIR/deploy/agentteams/resources-local-v1.1.2.yaml" \
    hiclaw-controller:/tmp/import/resources.yaml >/dev/null
  local role_name
  for role_name in manager curator judge; do
    docker cp "$ROOT_DIR/deploy/agentteams/dist/agentrig-$role_name.zip" \
      "hiclaw-controller:/tmp/import/agentrig-$role_name.zip" >/dev/null
  done
  docker exec hiclaw-controller hiclaw apply -f /tmp/import/resources.yaml
  for role_name in curator judge; do
    docker exec hiclaw-controller hiclaw apply worker \
      --name "agentrig-$role_name" \
      --zip "/tmp/import/agentrig-$role_name.zip" \
      --runtime openclaw
  done
  for attempt in $(seq 1 180); do
    if test "$(docker exec hiclaw-controller hiclaw get workers -o json \
      2>/dev/null | jq '[.workers[] | select(.phase == "Running")] | length')" -eq 2 \
      && docker exec hiclaw-worker-agentrig-curator \
        test -f /root/hiclaw-fs/agents/agentrig-curator/skills/simulate-tool-result/SKILL.md \
        2>/dev/null \
      && docker exec hiclaw-worker-agentrig-judge \
        test -f /root/hiclaw-fs/agents/agentrig-judge/skills/judge-evidence/SKILL.md \
        2>/dev/null; then
      break
    fi
    sleep 1
    test "$attempt" -lt 180 || die "AgentTeams Worker packages did not converge"
  done

  # The embedded v1.1.2 Manager named `default` pulls its live workspace from the
  # `manager/` object-storage prefix. Install the overlay after CR reconciliation,
  # publish it to that canonical prefix, and only then restart the runtime.
  (cd "$ROOT_DIR" && uv run python scripts/sync_agentteams_manager_workspace.py \
    --workspace "$HICLAW_WORKSPACE_DIR")
  for role_name in AGENTS.md SOUL.md; do
    docker exec hiclaw-manager mc cp \
      "/root/manager-workspace/$role_name" \
      "hiclaw/hiclaw-storage/manager/$role_name" >/dev/null
  done
  for role_name in \
    plan-evaluation \
    execute-evaluation-plan \
    diagnose-run \
    build-test-case-draft \
    configure-test-target; do
    docker exec hiclaw-manager mc mirror \
      "/root/manager-workspace/skills/$role_name/" \
      "hiclaw/hiclaw-storage/manager/skills/$role_name/" --overwrite >/dev/null
  done
  docker restart hiclaw-manager \
    hiclaw-worker-agentrig-curator \
    hiclaw-worker-agentrig-judge >/dev/null
  for attempt in $(seq 1 60); do
    if docker exec hiclaw-manager \
      grep -q 'AgentRig request envelope' /root/manager-workspace/AGENTS.md \
      2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  die "AgentRig Manager overlay did not survive runtime restart"
}

configure_matrix() {
  log "configuring the AgentRig Matrix bridge identity and fallback Worker room"
  local login_payload login_response bridge_token bridge_user
  local manager_user workers curator_user judge_user fallback_room old_fallback
  login_payload=$(jq -nc \
    --arg user "$HICLAW_ADMIN_USER" \
    --arg password "$HICLAW_ADMIN_PASSWORD" \
    '{type:"m.login.password",identifier:{type:"m.id.user",user:$user},password:$password}')
  login_response=$(curl -fsS -X POST "$MATRIX_BASE/_matrix/client/v3/login" \
    -H 'Content-Type: application/json' -d "$login_payload")
  bridge_token=$(printf '%s' "$login_response" | jq -er '.access_token')
  bridge_user=$(printf '%s' "$login_response" | jq -er '.user_id')
  manager_user=$(docker exec hiclaw-controller hiclaw get managers default -o json \
    | jq -er '.matrixUserID')
  workers=$(docker exec hiclaw-controller hiclaw get workers -o json)
  curator_user=$(printf '%s' "$workers" | jq -er \
    '.workers[] | select(.name=="agentrig-curator") | .matrixUserID')
  judge_user=$(printf '%s' "$workers" | jq -er \
    '.workers[] | select(.name=="agentrig-judge") | .matrixUserID')

  old_fallback=${AGENTRIG_AGENTTEAMS__MATRIX__DEFAULT_WORKER_ROOM_ID:-}
  fallback_room=""
  if test -n "$old_fallback"; then
    local encoded_old
    encoded_old=$(jq -rn --arg value "$old_fallback" '$value|@uri')
    if curl -fsS -H "Authorization: Bearer $bridge_token" \
      "$MATRIX_BASE/_matrix/client/v3/rooms/$encoded_old/state" >/dev/null 2>&1; then
      fallback_room=$old_fallback
    fi
  fi
  if test -z "$fallback_room"; then
    local room_payload room_response
    room_payload=$(jq -nc \
      --arg manager "$manager_user" \
      --arg curator "$curator_user" \
      --arg judge "$judge_user" \
      '{preset:"private_chat",name:"AgentRig local worker fallback",topic:"AgentRig V1 Core fallback Worker tasks",invite:[$manager,$curator,$judge],is_direct:false}')
    room_response=$(curl -fsS -X POST "$MATRIX_BASE/_matrix/client/v3/createRoom" \
      -H 'Content-Type: application/json' \
      -H "Authorization: Bearer $bridge_token" -d "$room_payload")
    fallback_room=$(printf '%s' "$room_response" | jq -er '.room_id')
  fi

  umask 077
  {
    printf 'AGENTRIG_MATRIX_ACCESS_TOKEN=%s\n' "$bridge_token"
    printf 'AGENTRIG_AGENTTEAMS__MATRIX__BRIDGE_USER_ID=%s\n' "$bridge_user"
    printf 'AGENTRIG_AGENTTEAMS__MATRIX__MANAGER_USER_ID=%s\n' "$manager_user"
    printf 'AGENTRIG_AGENTTEAMS__MATRIX__CURATOR_USER_ID=%s\n' "$curator_user"
    printf 'AGENTRIG_AGENTTEAMS__MATRIX__JUDGE_USER_ID=%s\n' "$judge_user"
    printf 'AGENTRIG_AGENTTEAMS__MATRIX__DEFAULT_WORKER_ROOM_ID=%s\n' "$fallback_room"
  } > "$RUNTIME_ENV"
  chmod 600 "$RUNTIME_ENV"
  load_local_env
}

login_higress() {
  local login_payload login_response
  login_payload=$(jq -nc \
    --arg username "$HICLAW_ADMIN_USER" \
    --arg password "$HICLAW_ADMIN_PASSWORD" \
    '{username:$username,password:$password}')
  umask 077
  login_response=$(curl -fsS -c "$HIGRESS_COOKIE" -X POST \
    "$HIGRESS_BASE/session/login" -H 'Content-Type: application/json' \
    -d "$login_payload")
  printf '%s' "$login_response" | jq -e '.name != null' >/dev/null
  chmod 600 "$HIGRESS_COOKIE"
  docker cp "$HIGRESS_COOKIE" hiclaw-controller:/tmp/agentrig-higress.cookie >/dev/null
}

route_exists() {
  local route_name=$1
  curl -fsS -b "$HIGRESS_COOKIE" \
    "$HIGRESS_BASE/v1/mcpServer?name=$route_name" \
    | jq -e --arg route "$route_name" \
      '.data | any(.name == $route)' >/dev/null
}

create_mcp_routes() {
  login_higress
  docker cp hiclaw-manager:/opt/hiclaw/scripts/lib/hiclaw-env.sh \
    "$ROOT_DIR/.agentrig/cache/hiclaw-env.sh" >/dev/null
  docker cp "$ROOT_DIR/.agentrig/cache/hiclaw-env.sh" \
    hiclaw-controller:/opt/hiclaw/scripts/lib/hiclaw-env.sh >/dev/null
  local proxy_script role_name role_token route_name
  proxy_script=/opt/hiclaw/agent/skills/mcp-server-management/scripts/setup-mcp-proxy.sh
  for role_name in manager curator judge; do
    case "$role_name" in
      manager) role_token=$AGENTRIG_MANAGER_MCP_TOKEN ;;
      curator) role_token=$AGENTRIG_CURATOR_MCP_TOKEN ;;
      judge) role_token=$AGENTRIG_JUDGE_MCP_TOKEN ;;
    esac
    route_name="mcp-agentrig-$role_name"
    if ! route_exists "$route_name"; then
      docker exec \
        -e HOME=/root/hiclaw-fs/agents/manager \
        -e HIGRESS_COOKIE_FILE=/tmp/agentrig-higress.cookie \
        -e HICLAW_AI_GATEWAY_DOMAIN=aigw-local.hiclaw.io \
        hiclaw-controller bash "$proxy_script" \
          "agentrig-$role_name" \
          "http://host.docker.internal:8010/mcp/$role_name/" http \
          --header "Authorization: Bearer $role_token" \
          > "$LOG_DIR/mcp-proxy-$role_name.log" 2>&1
    fi
  done
}

restrict_route() {
  local route_name=$1
  local keep_consumer=$2
  local current remove_consumers remove_count delete_payload delete_code add_payload add_code
  current=$(curl -fsS -b "$HIGRESS_COOKIE" \
    "$HIGRESS_BASE/v1/mcpServer/consumers?mcpServerName=$route_name")
  remove_consumers=$(printf '%s' "$current" | jq -c --arg keep "$keep_consumer" \
    '[.data[]?.consumerName | select(. != $keep)]')
  remove_count=$(printf '%s' "$remove_consumers" | jq 'length')
  if test "$remove_count" -gt 0; then
    delete_payload=$(jq -nc --arg route "$route_name" \
      --argjson consumers "$remove_consumers" \
      '{mcpServerName:$route,consumers:$consumers}')
    delete_code=$(curl -sS -o /dev/null -w '%{http_code}' -X DELETE \
      "$HIGRESS_BASE/v1/mcpServer/consumers" -b "$HIGRESS_COOKIE" \
      -H 'Content-Type: application/json' -d "$delete_payload")
    test "$delete_code" = 204 || die "failed to remove consumers from $route_name"
  fi
  add_payload=$(jq -nc --arg route "$route_name" --arg consumer "$keep_consumer" \
    '{mcpServerName:$route,consumers:[$consumer]}')
  add_code=$(curl -sS -o /dev/null -w '%{http_code}' -X PUT \
    "$HIGRESS_BASE/v1/mcpServer/consumers" -b "$HIGRESS_COOKIE" \
    -H 'Content-Type: application/json' -d "$add_payload")
  test "$add_code" = 204 || die "failed to authorize $keep_consumer on $route_name"
}

align_role_tokens() {
  local consumers
  consumers=$(curl -fsS -b "$HIGRESS_COOKIE" "$HIGRESS_BASE/v1/consumers")
  export LOCAL_MANAGER_GATEWAY_KEY LOCAL_CURATOR_GATEWAY_KEY LOCAL_JUDGE_GATEWAY_KEY
  LOCAL_MANAGER_GATEWAY_KEY=$(printf '%s' "$consumers" | jq -er \
    '.data[] | select(.name=="manager") | .credentials[] | select(.type=="key-auth") | .values[0]')
  LOCAL_CURATOR_GATEWAY_KEY=$(printf '%s' "$consumers" | jq -er \
    '.data[] | select(.name=="worker-agentrig-curator") | .credentials[] | select(.type=="key-auth") | .values[0]')
  LOCAL_JUDGE_GATEWAY_KEY=$(printf '%s' "$consumers" | jq -er \
    '.data[] | select(.name=="worker-agentrig-judge") | .credentials[] | select(.type=="key-auth") | .values[0]')
  perl -i -pe '
    if (/^AGENTRIG_MANAGER_MCP_TOKEN=/) { $_ = "AGENTRIG_MANAGER_MCP_TOKEN=$ENV{LOCAL_MANAGER_GATEWAY_KEY}\n" }
    if (/^AGENTRIG_CURATOR_MCP_TOKEN=/) { $_ = "AGENTRIG_CURATOR_MCP_TOKEN=$ENV{LOCAL_CURATOR_GATEWAY_KEY}\n" }
    if (/^AGENTRIG_JUDGE_MCP_TOKEN=/) { $_ = "AGENTRIG_JUDGE_MCP_TOKEN=$ENV{LOCAL_JUDGE_GATEWAY_KEY}\n" }
  ' "$LOCAL_ENV"
  chmod 600 "$LOCAL_ENV"
  load_local_env
}

configure_mcp() {
  log "configuring three role-isolated Higress MCP routes"
  create_mcp_routes
  restrict_route mcp-agentrig-manager manager
  restrict_route mcp-agentrig-curator worker-agentrig-curator
  restrict_route mcp-agentrig-judge worker-agentrig-judge
  align_role_tokens
}

stop_listener() {
  local port_number=$1
  local expected_text=$2
  local process_id process_command
  process_id=$(lsof -tiTCP:"$port_number" -sTCP:LISTEN 2>/dev/null | head -1 || true)
  test -z "$process_id" && return
  process_command=$(ps -p "$process_id" -o command=)
  case "$process_command" in
    *"$expected_text"*) ;;
    *) die "port $port_number belongs to another process: $process_command" ;;
  esac
  kill -TERM "$process_id"
  local attempt
  # Matrix sync uses a 20-second long poll. Allow the application shutdown hook
  # to drain it and close repositories instead of treating a normal drain as a
  # hung process after only ten seconds.
  for attempt in $(seq 1 120); do
    kill -0 "$process_id" 2>/dev/null || return 0
    sleep 0.25
  done
  # A browser can keep the assistant SSE connection open after uvicorn starts
  # graceful shutdown. The target PID and command were validated above, so use a
  # bounded fallback instead of leaving a second Matrix sync process behind.
  log "process on port $port_number did not drain in 30s; forcing the validated PID to stop"
  kill -KILL "$process_id"
  for attempt in $(seq 1 20); do
    kill -0 "$process_id" 2>/dev/null || return 0
    sleep 0.1
  done
  die "process on port $port_number did not stop after SIGKILL"
}

start_lassist() {
  if curl -fsS "$LASSIST_URL/health" >/dev/null 2>&1; then
    return
  fi
  screen -S agentrig-local-demo-lassist -X quit >/dev/null 2>&1 || true
  screen -dmS agentrig-local-demo-lassist bash -lc \
    "exec '$ROOT_DIR/scripts/run_lassist_local.sh' >> '$LOG_DIR/lassist.log' 2>&1"
  # lassist initializes its external PostgreSQL-backed state during startup and
  # can exceed one minute after a cold restart.
  wait_http "$LASSIST_URL/health" lassist 240
}

start_agentrig() {
  if curl -fsS "$AGENTRIG_URL/api/v2/agentteams/health" >/dev/null 2>&1; then
    return
  fi
  screen -S agentrig-local-demo-server -X quit >/dev/null 2>&1 || true
  screen -dmS agentrig-local-demo-server bash -lc \
    "exec '$ROOT_DIR/scripts/run_agentrig_local.sh' >> '$LOG_DIR/agentrig.log' 2>&1"
  wait_http "$AGENTRIG_URL/api/v2/agentteams/health" AgentRig
}

build_and_migrate() {
  log "building the Web UI and upgrading the local AgentRig database"
  (cd "$ROOT_DIR" && npm run build --prefix web >/dev/null)
  (cd "$ROOT_DIR" && uv run agentrig db upgrade)
}

start_services() {
  prepare_files
  load_local_env
  start_lassist
  build_and_migrate
  start_agentrig
}

restart_services() {
  log "restarting the two repository-owned local services"
  stop_listener 8010 'agentrig serve'
  stop_listener 8000 'start_server.py'
  screen -S agentrig-local-demo-server -X quit >/dev/null 2>&1 || true
  screen -S agentrig-local-demo-lassist -X quit >/dev/null 2>&1 || true
  start_services
}

start_existing_stack() {
  local controller_count
  prepare_files
  load_local_env
  ensure_docker
  controller_count=$(docker ps -a --format '{{.Names}}' \
    | awk '$0 == "hiclaw-controller" { count += 1 } END { print count + 0 }')
  test "$controller_count" -eq 1 \
    || die "AgentTeams is not installed; run scripts/local_demo.sh setup first"
  docker start hiclaw-controller >/dev/null 2>&1 || true
  wait_agentteams
  start_services
}

seed_demo() {
  prepare_files
  load_local_env
  (cd "$ROOT_DIR" && uv run python scripts/seed_local_demo.py)
}

verify_mcp_route() {
  local role_name=$1
  local accepted_token=$2
  local rejected_token=$3
  local route_url accepted_code rejected_code request_body
  route_url="$MATRIX_BASE/mcp-servers/mcp-agentrig-$role_name/mcp"
  request_body='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"agentrig-local-verify","version":"1"}}}'
  accepted_code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$route_url" \
    -H 'Host: aigw-local.hiclaw.io' \
    -H 'Accept: application/json, text/event-stream' \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $accepted_token" \
    -d "$request_body")
  test "$accepted_code" = 200 \
    || die "$role_name MCP route failed with HTTP $accepted_code"
  rejected_code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "$route_url" \
    -H 'Host: aigw-local.hiclaw.io' \
    -H 'Accept: application/json, text/event-stream' \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $rejected_token" \
    -d "$request_body")
  case "$rejected_code" in
    401|403) ;;
    *) die "$role_name MCP route accepted a different role (HTTP $rejected_code)" ;;
  esac
}

verify_demo() {
  prepare_files
  load_local_env
  docker info >/dev/null 2>&1 || die "Docker Desktop is unavailable"
  curl -fsS "$LASSIST_URL/health" >/dev/null || die "lassist health failed"
  local health v2_routes
  health=$(curl -fsS "$AGENTRIG_URL/api/v2/agentteams/health")
  printf '%s' "$health" | jq -e \
    '.enabled and .configured and .matrix_reachable' >/dev/null \
    || die "AgentTeams bridge health failed"
  v2_routes=$(curl -fsS "$AGENTRIG_URL/openapi.json" \
    | jq '[.paths | keys[] | select(startswith("/api/v2"))] | length')
  test "$v2_routes" -ge 18 || die "V2 routes are incomplete"
  curl -fsS "$AGENTRIG_URL/api/targets/target_lassist_local" \
    | jq -e '.driver_type == "pixcake_http_sse"' >/dev/null \
    || die "local lassist Target is missing"
  curl -fsS "$AGENTRIG_URL/api/test-cases/case_lassist_three_agent_demo" \
    | jq -e '.review_status == "approved"' >/dev/null \
    || die "positive demo Case is missing or not approved"
  curl -fsS "$AGENTRIG_URL/api/test-cases/case_lassist_confirmation_gate_failure" \
    | jq -e '.review_status == "approved"' >/dev/null \
    || die "negative security Case is missing or not approved"
  curl -fsS "$AGENTRIG_URL/targets/target_lassist_local/conversation" \
    | grep -qi '<!doctype html' \
    || die "Target conversation Web UI is unavailable"
  test "$(docker exec hiclaw-controller hiclaw get workers -o json \
    | jq '[.workers[] | select(.phase == "Running")] | length')" -eq 2 \
    || die "AgentTeams Workers are not running"
  docker exec hiclaw-manager \
    grep -q 'AgentRig request envelope' /root/manager-workspace/AGENTS.md \
    || die "AgentRig Manager contract is not installed"
  docker exec hiclaw-manager \
    test -f /root/manager-workspace/skills/plan-evaluation/SKILL.md \
    || die "AgentRig Manager Skills are not installed"
  docker exec hiclaw-worker-agentrig-curator \
    test -f /root/hiclaw-fs/agents/agentrig-curator/skills/simulate-tool-result/SKILL.md \
    || die "Simulation Curator Skill is not installed"
  docker exec hiclaw-worker-agentrig-judge \
    test -f /root/hiclaw-fs/agents/agentrig-judge/skills/judge-evidence/SKILL.md \
    || die "Evidence Judge Skill is not installed"
  verify_mcp_route manager \
    "$AGENTRIG_MANAGER_MCP_TOKEN" "$AGENTRIG_JUDGE_MCP_TOKEN"
  verify_mcp_route curator \
    "$AGENTRIG_CURATOR_MCP_TOKEN" "$AGENTRIG_MANAGER_MCP_TOKEN"
  verify_mcp_route judge \
    "$AGENTRIG_JUDGE_MCP_TOKEN" "$AGENTRIG_CURATOR_MCP_TOKEN"
  log "verification passed: lassist + AgentRig V2 + Matrix + three AgentTeams roles"
}

setup_all() {
  prepare_files
  load_local_env
  ensure_docker
  install_agentteams
  wait_agentteams
  apply_resources
  configure_matrix
  configure_mcp
  # Role tokens and Matrix identities are materialized during setup, so an already
  # running process must be replaced before the acceptance checks.
  restart_services
  seed_demo
  verify_demo
}

stop_all() {
  stop_listener 8010 'agentrig serve'
  stop_listener 8000 'start_server.py'
  screen -S agentrig-local-demo-server -X quit >/dev/null 2>&1 || true
  screen -S agentrig-local-demo-lassist -X quit >/dev/null 2>&1 || true
  if docker info >/dev/null 2>&1; then
    local container_name
    for container_name in \
      hiclaw-worker-agentrig-curator \
      hiclaw-worker-agentrig-judge \
      hiclaw-manager \
      hiclaw-controller; do
      docker stop "$container_name" >/dev/null 2>&1 || true
    done
  fi
  log "local demo stopped; databases and Docker volumes were preserved"
}

show_status() {
  printf 'lassist: '
  curl -fsS "$LASSIST_URL/health" >/dev/null 2>&1 && echo ready || echo unavailable
  printf 'AgentRig: '
  curl -fsS "$AGENTRIG_URL/api/v2/agentteams/health" 2>/dev/null \
    | jq -c '{enabled,configured,matrix_reachable,message}' || echo unavailable
  printf 'Docker: '
  command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 \
    && echo ready || echo unavailable
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    docker ps -a --format '{{.Names}}\t{{.Status}}' | grep '^hiclaw-' | sort || true
  fi
  printf 'Web: %s/targets/target_lassist_local/conversation\n' "$AGENTRIG_URL"
}

open_demo() {
  local conversation_url="$AGENTRIG_URL/targets/target_lassist_local/conversation"
  open "$conversation_url"
  log "opened $conversation_url"
}

usage() {
  cat <<'EOF'
Usage: scripts/local_demo.sh <command>

  setup    Install/configure AgentTeams, start services, seed and verify everything
  start    Start the existing AgentTeams installation, lassist and AgentRig
  restart  Rebuild and restart lassist/AgentRig, then seed and verify
  seed     Idempotently create the local Target, approved Case and Profile
  verify   Run local health and contract acceptance checks
  open     Open the lassist Target conversation window
  status   Show service/container status
  stop     Stop only this demo; preserve databases, containers and volumes
  all      Alias for setup, followed by opening the assistant window
EOF
}

command_name=${1:-status}
case "$command_name" in
  setup) setup_all ;;
  start) start_existing_stack ;;
  restart) restart_services; seed_demo; verify_demo ;;
  seed) seed_demo ;;
  verify) verify_demo ;;
  open) open_demo ;;
  status) show_status ;;
  stop) stop_all ;;
  all) setup_all; open_demo ;;
  *) usage; exit 2 ;;
esac
