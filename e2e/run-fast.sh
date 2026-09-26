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

echo "[$(date -u +%FT%TZ)] compose config"
$compose config > "$log_dir/compose-config.txt"

echo "[$(date -u +%FT%TZ)] building fast E2E services"
$compose build --progress=plain 2>&1 | tee "$log_dir/build.log"

cleanup() {
  echo "[$(date -u +%FT%TZ)] final compose state"
  $compose ps || true
  $compose logs --no-color --timestamps || true
  $compose down -v || true
}
trap cleanup EXIT

echo "[$(date -u +%FT%TZ)] starting fast E2E services"
$compose up -d

until curl -fsS http://localhost:18000/api/v1/health >/dev/null; do
  $compose ps
  sleep 2
done
until curl -fsS http://localhost:18001/healthz >/dev/null; do
  $compose ps
  sleep 2
done

echo "[$(date -u +%FT%TZ)] calling agent"
curl -fsS   -X POST   -H "Content-Type: application/json"   -d '{"message":"Find the RAG E2E marker."}'   http://localhost:18000/api/v1/chat | tee "$log_dir/chat.json"

grep -q 'RAG_E2E_OK' "$log_dir/chat.json"
echo "[$(date -u +%FT%TZ)] fast E2E passed"
