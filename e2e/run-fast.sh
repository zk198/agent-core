#!/usr/bin/env sh
set -eu

: "${RAG_JWT_SECRET:?RAG_JWT_SECRET is required}"

export RAG_E2E_TOKEN="$(python - <<'PY'
import base64
import hashlib
import hmac
import json
import os

def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
payload = b64(json.dumps(
    {"tenant_id": "e2e-tenant", "sub": "e2e-user"},
    separators=(",", ":"),
).encode())
signing_input = f"{header}.{payload}".encode()
signature = hmac.new(
    os.environ["RAG_JWT_SECRET"].encode(),
    signing_input,
    hashlib.sha256,
).digest()
print(f"{header}.{payload}.{b64(signature)}")
PY
)"

compose="docker compose -f e2e/fast-compose.yaml"
log_dir="${RUNNER_TEMP:-/tmp}/rag-e2e-fast"
mkdir -p "$log_dir"

log() {
  echo "[$(date -u +%FT%TZ)] $*"
}

dump_state() {
  log "compose state"
  $compose ps || true
  log "compose images"
  $compose images || true
  log "compose logs"
  $compose logs --no-color --timestamps || true
}

wait_for() {
  name="$1"
  url="$2"
  deadline=$(($(date +%s) + 60))
  log "waiting for $name: $url"
  while ! curl -fsS --max-time 2 "$url" >/dev/null; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      log "timeout waiting for $name"
      dump_state
      return 1
    fi
    sleep 2
  done
  log "$name ready"
}

log "compose config"
$compose config > "$log_dir/compose-config.txt"

build() {
  log "building fast E2E services"
  $compose build --progress=plain "$@" 2>&1 | tee "$log_dir/build.log"
}

start_mocks() {
  log "starting mock LLM"
  $compose up -d mock-llm
  log "starting mock retrieval"
  $compose up -d mock-retrieval
}
start_gateway() {
  log "starting AI gateway"
  $compose up -d ai-gateway
}
start_agent() {
  log "starting agent-core"
  $compose up -d agent-core
}
wait_agent() { wait_for "agent-core" "http://localhost:18000/api/v1/health"; }
wait_gateway() { wait_for "ai-gateway (host 18001 -> container 8200)" "http://localhost:18001/health"; }

gateway_chat() {
  log "calling agent through ai-gateway session boundary"
  curl -fsS --max-time 60     -X POST     -H "Content-Type: application/json"     -H "Authorization: Bearer $RAG_E2E_TOKEN"     -d '{"messages":[{"role":"user","content":"Find the RAG E2E marker."}]}'     http://localhost:18001/v1/chat/completions | tee "$log_dir/gateway-chat.json"
  grep -q 'RAG_E2E_OK' "$log_dir/gateway-chat.json"
  grep -q '"conversation_id"' "$log_dir/gateway-chat.json"
  log "gateway session E2E passed"
}

discover() {
  log "discovering MCP tools through agent-core"
  curl -fsS --max-time 30 http://localhost:18000/api/v1/tools | tee "$log_dir/tools.json"
}

chat() {
  log "calling agent"
  curl -fsS --max-time 60 \
    -X POST \
    -H "Content-Type: application/json" \
    -d '{"message":"Find the RAG E2E marker."}' \
    http://localhost:18000/api/v1/chat | tee "$log_dir/chat.json"
  grep -q 'RAG_E2E_OK' "$log_dir/chat.json"
  log "fast E2E passed"
}

stream() {
  log "calling grounded answer stream"
  curl -fsS --max-time 60 \
    -X POST \
    -H "Content-Type: application/json" \
    -d '{"question":"Find the RAG E2E marker."}' \
    http://localhost:18000/api/v1/answer/stream | tee "$log_dir/answer-stream.txt"
  grep -q 'RAG_E2E_STREAM_OK' "$log_dir/answer-stream.txt"
  grep -q 'event: done' "$log_dir/answer-stream.txt"
  log "grounded answer stream passed"
}

cleanup() {
  log "final compose state"
  dump_state
  $compose down -v || true
}

case "${1:-all}" in
  build) build ;;
  start-mocks) start_mocks ;;
  start-gateway) start_gateway ;;
  start-agent) start_agent ;;
  start) start_mocks; start_gateway; start_agent ;;
  wait-agent) wait_agent ;;
  wait-gateway) wait_gateway ;;
  discover) discover ;;
  chat) chat ;;
  gateway-chat) gateway_chat ;;
  stream) stream ;;
  cleanup) cleanup ;;
  all)
    trap cleanup EXIT
    build
    start
    discover
    chat
    ;;
  *)
    echo "usage: $0 [build|start-mocks|start-gateway|start-agent|start|wait-agent|wait-gateway|discover|chat|gateway-chat|stream|cleanup|all]" >&2
    exit 2
    ;;
esac
