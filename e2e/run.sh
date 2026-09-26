#!/usr/bin/env sh
set -eu

: "${RAG_JWT_SECRET:?RAG_JWT_SECRET is required}"

export RAG_E2E_TOKEN="$(python - <<'PY'
import base64, hashlib, hmac, json, os

def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()

header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
payload = b64(json.dumps({"tenant_id": "e2e-tenant", "sub": "e2e-user"}, separators=(",", ":")).encode())
signing_input = f"{header}.{payload}".encode()
signature = hmac.new(os.environ["RAG_JWT_SECRET"].encode(), signing_input, hashlib.sha256).digest()
print(f"{header}.{payload}.{b64(signature)}")
PY
)"

export AGENT_MODEL_BASE_URL="http://mock-llm:8080/v1"
export AGENT_MODEL_API_KEY="e2e"
export AGENT_MODEL_NAME="e2e/mock"
export AGENT_MCP_SERVER_NAMES="rag"
export AGENT_MCP_SERVERS="http://ai-gateway:8200/mcp/"
export AGENT_MCP_AUTH_TOKENS="$RAG_E2E_TOKEN"
export AI_GATEWAY_PORT="18001"

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
export AGENT_CORE_DIR="$(CDPATH= cd -- "$script_dir/.." && pwd)"
compose="docker compose -f $script_dir/../../rag-infra/compose.yaml -f $script_dir/compose.yaml"
log_dir="${RUNNER_TEMP:-/tmp}/rag-e2e-full"
mkdir -p "$log_dir"

log() { echo "[$(date -u +%FT%TZ)] $*"; }

dump_state() {
  log "compose ps"
  $compose ps || true
  log "compose service status"
  docker ps --format 'table {{.Names}}	{{.Status}}	{{.Ports}}' || true
  for service in postgres qdrant pst-agent rag-indexer rag-retrieval ai-gateway agent-core mock-llm; do
    log "logs: $service"
    $compose logs --no-color --timestamps --tail=200 "$service" || true
  done
}

wait_for() {
  name="$1"
  url="$2"
  deadline=$(($(date +%s) + 180))
  log "waiting for $name: $url"
  while ! curl -fsS --max-time 3 "$url" >/dev/null; do
    if [ "$(date +%s)" -ge "$deadline" ] || [ "$(date +%s)" -ge "$overall_deadline" ]; then
      log "timeout waiting for $name"
      dump_state
      exit 1
    fi
    sleep 2
  done
  log "$name ready"
}

cleanup() {
  log "final service state"
  dump_state
  $compose down -v || true
}
trap cleanup EXIT

log "compose config"
$compose config > "$log_dir/compose-config.txt"

log "building focused full RAG path"
timeout 300s sh -c "$compose build --progress=plain postgres qdrant pst-agent rag-indexer rag-retrieval ai-gateway agent-core mock-llm" 2>&1 | tee "$log_dir/build.log"

log "starting focused full RAG path"
timeout 180s sh -c "$compose up -d postgres qdrant pst-agent rag-indexer rag-retrieval mock-llm agent-core ai-gateway"
overall_deadline=$(($(date +%s) + 480))

wait_for_agent() {
  deadline=$(($(date +%s) + 180))
  log "waiting for agent-core"
  while ! $compose exec -T agent-core python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health", timeout=2)' >/dev/null 2>&1; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      log "timeout waiting for agent-core"
      dump_state
      exit 1
    fi
    sleep 2
  done
  log "agent-core ready"
}
wait_for_agent
wait_for "ai-gateway (host 18001 -> container 8200)" "http://localhost:18001/health"

log "uploading marker"
printf 'RAG_E2E_MARKER: integration path from agent-core through MCP into indexed RAG content.\n' > /tmp/rag-e2e.txt
curl -fsS --max-time 15   -X POST   -H "Authorization: Bearer ${RAG_E2E_TOKEN}"   -F "file=@/tmp/rag-e2e.txt"   -F "source_name=e2e"   http://localhost:18001/upload | tee "$log_dir/upload.json"

log "waiting for indexed marker"
i=0
while [ "$i" -lt 20 ]; do
  log "retrieval poll $i/20"
  if curl -fsS --max-time 10       -X POST       -H "Authorization: Bearer ${RAG_E2E_TOKEN}"       -H "Content-Type: application/json"       -d '{"query":"RAG_E2E_MARKER","limit":3}'       http://localhost:18001/search | tee "$log_dir/search-$i.json" | grep -q 'RAG_E2E_MARKER'; then
    break
  fi
  i=$((i + 1))
  if [ $((i % 10)) -eq 0 ]; then
    log "retrieval still waiting; service status"
    $compose ps || true
    for service in pst-agent rag-indexer rag-retrieval ai-gateway; do
      log "recent logs: $service"
      $compose logs --no-color --timestamps --tail=40 "$service" || true
    done
  fi
  sleep 2
done
[ "$i" -lt 20 ]

log "marker indexed; calling agent directly"
$compose exec -T agent-core python -c 'import httpx; r=httpx.post("http://127.0.0.1:8000/api/v1/chat", json={"message":"Find the RAG E2E marker."}, timeout=60); print(r.text); r.raise_for_status()' | tee "$log_dir/agent-chat.json"
grep -q 'RAG_E2E_OK' "$log_dir/agent-chat.json"

log "calling agent through ai-gateway"
curl -fsS --max-time 60   -X POST   -H "Authorization: Bearer ${RAG_E2E_TOKEN}"   -H "Content-Type: application/json"   -d '{"messages":[{"role":"user","content":"Find the RAG E2E marker."}]}'   http://localhost:18001/v1/chat/completions | tee "$log_dir/gateway-chat.json"
grep -q 'RAG_E2E_OK' "$log_dir/gateway-chat.json"
grep -q '"conversation_id"' "$log_dir/gateway-chat.json"

log "full RAG + MCP + agent + gateway E2E passed"
