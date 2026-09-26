#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
export AGENT_CORE_DIR="$(CDPATH= cd -- "$script_dir/.." && pwd)"
: "${AGENT_TOOLS_WEB_DIR:?AGENT_TOOLS_WEB_DIR is required}"

compose="docker compose -f $script_dir/tools-web-compose.yaml"
log_dir="${RUNNER_TEMP:-/tmp}/e2e-tools-web"
mkdir -p "$log_dir"

dump_state() {
  $compose ps || true
  for service in mock-llm mock-search searxng web agent-core; do
    $compose logs --no-color --timestamps --tail=120 "$service" || true
  done
}

cleanup() {
  dump_state
  $compose down -v || true
}
trap cleanup EXIT

$compose config > "$log_dir/compose-config.txt"
timeout 300s sh -c "$compose build --progress=plain" 2>&1 | tee "$log_dir/build.log"
timeout 180s sh -c "$compose up -d" 2>&1 | tee "$log_dir/up.log"

for service in mock-llm mock-search searxng web agent-core; do
  deadline=$(($(date +%s) + 180))
  while ! $compose exec -T "$service" sh -c 'true' >/dev/null 2>&1; do
    [ "$(date +%s)" -lt "$deadline" ] || { echo "timeout waiting for $service"; exit 1; }
    sleep 2
  done
done

wait_http() {
  name="$1"
  url="$2"
  deadline=$(($(date +%s) + 180))
  while ! $compose exec -T web python -c "import urllib.request; urllib.request.urlopen('$url', timeout=5).read()" >/dev/null 2>&1; do
    [ "$(date +%s)" -lt "$deadline" ] || { echo "timeout waiting for $name"; dump_state; exit 1; }
    sleep 2
  done
}
wait_http "SearXNG" "http://searxng:8080/search?q=E2E_TOOLS_WEB_MARKER&format=json"
wait_http "web tool" "http://127.0.0.1:8000/health"
check_mcp() {
  url="$1"
  expected="$2"
  $compose exec -T agent-core python - "$url" "$expected" <<'PY'
import asyncio
import sys
from fastmcp import Client

async def main() -> None:
    async with Client(sys.argv[1]) as client:
        names = [tool.name for tool in await client.list_tools()]
        assert sys.argv[2] in names, names

asyncio.run(main())
PY
}
wait_mcp() {
  name="$1"
  url="$2"
  expected="$3"
  deadline=$(($(date +%s) + 180))
  while ! check_mcp "$url" "$expected" >/dev/null 2>&1; do
    [ "$(date +%s)" -lt "$deadline" ] || { echo "timeout waiting for $name MCP"; dump_state; exit 1; }
    sleep 2
  done
}
wait_mcp "web MCP" "http://web:8001/mcp/" "web_search"
$compose exec -T web python -c 'import urllib.request; print(urllib.request.urlopen("http://searxng:8080/search?q=E2E_TOOLS_WEB_MARKER&format=json", timeout=10).read().decode())' > "$log_dir/searxng.json"
grep -q 'E2E_TOOLS_WEB_MARKER' "$log_dir/searxng.json"

$compose exec -T agent-core python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health", timeout=10).read()'

$compose exec -T agent-core python -c '
import httpx
r=httpx.post("http://127.0.0.1:8000/api/v1/chat", json={"message":"Search the web for E2E_TOOLS_WEB_MARKER."}, timeout=60)
print(r.text)
r.raise_for_status()
assert "WEB_E2E_OK" in r.text
' | tee "$log_dir/agent-chat.json"

echo "e2e tools web passed"

# rerun after MCP ASGI deployment fix
