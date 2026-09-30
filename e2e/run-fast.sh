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
export RAG_DIAGNOSTICS_TOKEN="$(python - <<'PY'
import base64
import hashlib
import hmac
import json
import os

def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
payload = b64(json.dumps(
    {"tenant_id": "e2e-tenant", "sub": "e2e-user", "permissions": ["diagnostics:read"]},
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
export RAG_OTHER_TENANT_DIAGNOSTICS_TOKEN="$(python - <<'PY'
import base64
import hashlib
import hmac
import json
import os

def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
payload = b64(json.dumps(
    {"tenant_id": "other-tenant", "sub": "e2e-user", "permissions": ["diagnostics:read"]},
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
  log "starting mock Laya"
  $compose up -d mock-laya
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
wait_gateway() { wait_for "ai-gateway" "http://localhost:18001/health"; }

laya_gateway() {
  log "calling privileged gateway System-1 boundary against mocked Laya"
  curl -fsS --max-time 30 \
    -X POST \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $RAG_DIAGNOSTICS_TOKEN" \
    -H "X-Request-ID: phase1d-laya-gateway" \
    -d '{"state":{"message":"classify this request"},"questions":{"request_type":{"type":"choice","instructions":"Classify the request type.","criteria":{"knowledge":"asks for information or explanation","action":"asks to perform or plan an action","other":"other"}}}}' \
    http://localhost:18001/api/v1/systemone | tee "$log_dir/laya-gateway.json"
  python - "$log_dir/laya-gateway.json" <<'PY'
import json
import sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload["answers"]["allowed"]["noul"] is True
assert payload["routing"]["model"] == "e2e/mock-laya"
assert payload["trace_id"]
PY
  log "gateway Laya boundary E2E passed"
}

laya_trace() {
  log "checking Laya System-1 trace through agent and gateway"
  python - "$log_dir/chat.json" <<'PY'
import json
import sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
events = payload["trace"]["trace"]
laya = [event for event in events if event.get("kind") == "system1" and event.get("stage") == "laya"]
assert laya, events
assert laya[0]["name"] == "laya.systemone"
assert laya[0]["payload"]["answers"]["allowed"]["noul"] is True
assert laya[0]["payload"]["routing"]["model"] == "e2e/mock-laya"
PY
  curl -fsS --max-time 30 \
    -X POST \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $RAG_E2E_TOKEN" \
    -d '{"question":"Check the Laya trace."}' \
    http://localhost:18001/api/v1/answer | tee "$log_dir/gateway-laya-answer.json"
  trace_id="$(python - "$log_dir/gateway-laya-answer.json" <<'PY'
import json
import sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(payload["trace_id"])
PY
)"
  test -n "$trace_id"
  curl -fsS --max-time 30 \
    -H "Authorization: Bearer $RAG_DIAGNOSTICS_TOKEN" \
    "http://localhost:18001/api/v1/traces/$trace_id" | tee "$log_dir/gateway-laya-trace.json"
  python - "$log_dir/gateway-laya-trace.json" <<'PY'
import json
import sys
trace = json.load(open(sys.argv[1], encoding="utf-8"))
events = trace["trace"]
laya = [event for event in events if event.get("kind") == "system1" and event.get("stage") == "laya"]
assert laya, events
assert laya[0]["payload"]["answers"]["allowed"]["noul"] is True
assert laya[0]["payload"]["routing"]["model"] == "e2e/mock-laya"
PY
  log "agent/gateway Laya trace propagation E2E passed"
}

gateway_chat() {
  log "calling agent through ai-gateway session boundary"
  curl -fsS --max-time 60     -X POST     -H "Content-Type: application/json"     -H "Authorization: Bearer $RAG_E2E_TOKEN"     -d '{"messages":[{"role":"user","content":"Find the RAG E2E marker."}]}'     http://localhost:18001/v1/chat/completions | tee "$log_dir/gateway-chat.json"
  grep -q 'RAG_E2E_OK' "$log_dir/gateway-chat.json"
  grep -q '"conversation_id"' "$log_dir/gateway-chat.json"
  log "gateway session E2E passed"
}

gateway_failure_diagnostics() {
  log "calling invalid MCP argument through ai-gateway"
  curl -fsS --max-time 60 \
    -X POST \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $RAG_E2E_TOKEN" \
    -d '{"question":"RAG_E2E_INVALID_ARGS"}' \
    http://localhost:18001/api/v1/answer/stream | tee "$log_dir/gateway-invalid-args.txt"
  grep -q 'event: error' "$log_dir/gateway-invalid-args.txt"
  trace_id="$(python - "$log_dir/gateway-invalid-args.txt" <<'PY'
import json
import sys

text = open(sys.argv[1], encoding="utf-8").read()
for frame in text.split("\n\n"):
    if frame.startswith("event: error\ndata: "):
        payload = json.loads(frame.split("data: ", 1)[1])
        print(payload["trace_id"])
        break
else:
    raise SystemExit("missing error trace_id")
PY
)"
  test -n "$trace_id"

  normal_status="$(curl -sS -o "$log_dir/diagnostics-normal.json" -w "%{http_code}" \
    -H "Authorization: Bearer $RAG_E2E_TOKEN" \
    "http://localhost:18001/api/v1/traces/$trace_id")"
  test "$normal_status" = "403"

  curl -fsS --max-time 30 \
    -H "Authorization: Bearer $RAG_DIAGNOSTICS_TOKEN" \
    "http://localhost:18001/api/v1/traces/$trace_id" | tee "$log_dir/diagnostic-trace.json"
  python - "$log_dir/diagnostic-trace.json" <<'PY'
import json
import sys

trace = json.load(open(sys.argv[1], encoding="utf-8"))
assert trace["status"] == "failed"
assert trace["error"]["type"] == "MCPToolArgumentError"
failed_tools = [
    event for event in trace["trace"]
    if event.get("kind") == "tool" and event.get("status") == "failed"
]
assert failed_tools, trace
PY

  other_status="$(curl -sS -o "$log_dir/diagnostics-other-tenant.json" -w "%{http_code}" \
    -H "Authorization: Bearer $RAG_OTHER_TENANT_DIAGNOSTICS_TOKEN" \
    "http://localhost:18001/api/v1/traces/$trace_id")"
  test "$other_status" = "404"
  log "gateway MCP argument failure diagnostics E2E passed"
}

gateway_stream() {
  log "calling grounded answer stream through ai-gateway"
  curl -fsS --max-time 60 \
    -X POST \
    -H "Content-Type: application/json" \
    -H "X-Request-ID: phase1c-e2e-request" \
    -H "Authorization: Bearer $RAG_E2E_TOKEN" \
    -d '{"question":"Find the RAG E2E marker."}' \
    http://localhost:18001/api/v1/answer/stream | tee "$log_dir/gateway-answer-stream.txt"
  grep -q 'event: delta' "$log_dir/gateway-answer-stream.txt"
  grep -q 'event: done' "$log_dir/gateway-answer-stream.txt"
  grep -q 'RAG_E2E_STREAM_OK' "$log_dir/gateway-answer-stream.txt"
  grep -q '"citations"' "$log_dir/gateway-answer-stream.txt"
  grep -q '"conversation_id"' "$log_dir/gateway-answer-stream.txt"
  log "gateway grounded answer stream passed"
  $compose logs --no-color ai-gateway agent-core > "$log_dir/observability.log"
  grep -q "request_id=phase1c-e2e-request" "$log_dir/observability.log"
  grep -q "gateway_request" "$log_dir/observability.log"
  grep -q "gateway_stream_stage" "$log_dir/observability.log"
  grep -q "agent_ms=" "$log_dir/observability.log"
  grep -Eq "stage=retrieval|stage=tool" "$log_dir/observability.log"
  grep -q "stage=llm" "$log_dir/observability.log"
  log "observability acceptance passed"
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
  laya-gateway) laya_gateway ;;
  laya-trace) laya_trace ;;
  gateway-stream) gateway_stream ;;
  gateway-failure-diagnostics) gateway_failure_diagnostics ;;
  stream) stream ;;
  cleanup) cleanup ;;
  all)
    trap cleanup EXIT
    build
    start
    discover
    chat
    laya_trace
    ;;
  *)
    echo "usage: $0 [build|start-mocks|start-gateway|start-agent|start|wait-agent|wait-gateway|discover|chat|gateway-chat|gateway-stream|gateway-failure-diagnostics|laya-gateway|laya-trace|stream|cleanup|all]" >&2
    exit 2
    ;;
esac
