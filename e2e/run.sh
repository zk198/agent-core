#!/usr/bin/env sh
set -eu

: "${RAG_JWT_SECRET:?RAG_JWT_SECRET is required}"

python -m pip install --quiet "PyJWT>=2.9,<3"

export RAG_E2E_TOKEN="$(python - <<'PY'
import os
import jwt

print(jwt.encode(
    {"tenant_id": "e2e-tenant", "sub": "e2e-user"},
    os.environ["RAG_JWT_SECRET"],
    algorithm="HS256",
))
PY
)"

compose="docker compose -f ../rag-infra/compose.yaml -f e2e/compose.yaml"
log_dir="${RUNNER_TEMP:-/tmp}/rag-e2e-full"
mkdir -p "$log_dir"

step() {
  echo
  echo "===== [$(date -u +%FT%TZ)] $* ====="
}

dump_state() {
  step "compose ps"
  $compose ps || true
  step "container status"
  docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' || true
  step "service logs"
  $compose logs --no-color --timestamps || true
}

cleanup() {
  dump_state
  $compose down -v || true
}
trap cleanup EXIT

step "compose config"
$compose config > "$log_dir/compose-config.txt"

step "building full RAG stack"
$compose build --progress=plain 2>&1 | tee "$log_dir/build.log"

step "starting full RAG stack"
$compose up -d

step "waiting for agent-core"
until curl -fsS http://localhost:18000/api/v1/health >/dev/null; do
  $compose ps
  sleep 2
done

step "waiting for gateway"
until curl -fsS http://localhost:18001/healthz >/dev/null; do
  $compose ps
  sleep 2
done

step "uploading marker"
printf 'RAG_E2E_MARKER: integration path from agent-core through MCP into indexed RAG content.\n' > /tmp/rag-e2e.txt
curl -fsS \
  -X POST \
  -H "Authorization: Bearer ${RAG_E2E_TOKEN}" \
  -F "file=@/tmp/rag-e2e.txt" \
  -F "source_name=e2e" \
  http://localhost:18001/upload | tee "$log_dir/upload.json"

step "waiting for indexed marker"
i=0
while [ "$i" -lt 120 ]; do
  echo "[$(date -u +%FT%TZ)] retrieval poll $i/120"
  if curl -fsS \
      -X POST \
      -H "Authorization: Bearer ${RAG_E2E_TOKEN}" \
      -H "Content-Type: application/json" \
      -d '{"query":"RAG_E2E_MARKER","limit":3}' \
      http://localhost:18001/search | tee "$log_dir/search-$i.json" | grep -q 'RAG_E2E_MARKER'; then
    break
  fi
  $compose ps
  i=$((i + 1))
  sleep 2
done

[ "$i" -lt 120 ]

step "calling agent"
curl -fsS \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"message":"Find the RAG E2E marker."}' \
  http://localhost:18000/api/v1/chat | tee "$log_dir/chat.json"

grep -q 'RAG_E2E_OK' "$log_dir/chat.json"
step "full RAG E2E passed"
