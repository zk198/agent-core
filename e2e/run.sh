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

docker compose -f ../rag-infra/compose.yaml -f compose.yaml up -d --build

cleanup() {
  docker compose -f ../rag-infra/compose.yaml -f compose.yaml down -v
}
trap cleanup EXIT

until curl -fsS http://localhost:18000/api/v1/health >/dev/null; do sleep 2; done
until curl -fsS http://localhost:18001/healthz >/dev/null; do sleep 2; done

printf 'RAG_E2E_MARKER: integration path from agent-core through MCP into indexed RAG content.\n' > /tmp/rag-e2e.txt

curl -fsS \
  -X POST \
  -H "Authorization: Bearer ${RAG_E2E_TOKEN}" \
  -F "file=@/tmp/rag-e2e.txt" \
  -F "source_name=e2e" \
  http://localhost:18001/upload >/tmp/upload.json

i=0
while [ "$i" -lt 120 ]; do
  if curl -fsS \
      -X POST \
      -H "Authorization: Bearer ${RAG_E2E_TOKEN}" \
      -H "Content-Type: application/json" \
      -d '{"query":"RAG_E2E_MARKER","limit":3}' \
      http://localhost:18001/search | grep -q 'RAG_E2E_MARKER'; then
    break
  fi
  i=$((i + 1))
  sleep 2
done

[ "$i" -lt 120 ]

curl -fsS \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"message":"Find the RAG E2E marker."}' \
  http://localhost:18000/api/v1/chat | tee /tmp/chat.json

grep -q 'RAG_E2E_OK' /tmp/chat.json
