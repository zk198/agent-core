# Agent Core

Generic agent orchestration service for the AI Platform. It connects an OpenAI-compatible model gateway to configured MCP servers, executes tool-assisted workflows and returns responses with trace information.

## Responsibilities
- Run chat/answer requests against the configured model gateway.
- Discover and invoke tools exposed by configured MCP servers.
- Expose discovered tool metadata for diagnostics.
- Support streaming responses and request/trace correlation.
- Optionally consult the Laya System-1 decision service when enabled.

## API
Routes are rooted under `/api/v1`:
- `GET /api/v1/health` — liveness.
- `GET /api/v1/ready` — readiness including MCP dependency availability.
- `GET /api/v1/tools` — discovered tool metadata.
- `POST /api/v1/chat` — chat and tool orchestration.

The service is internal; client traffic should enter through `ai-gateway`.

## Configuration
- `AGENT_MODEL_BASE_URL`, `AGENT_MODEL_API_KEY`, `AGENT_MODEL_NAME` — OpenAI-compatible model gateway.
- `AGENT_MCP_SERVER_NAMES`, `AGENT_MCP_SERVERS`, `AGENT_MCP_AUTH_TOKENS` — MCP registry and access.
- `AGENT_LAYA_ENABLED`, `AGENT_LAYA_URL`, `AGENT_LAYA_TIMEOUT_SECONDS`, `AGENT_LAYA_API_KEY`, `AGENT_LAYA_QUESTIONS_JSON`, `AGENT_LAYA_ENFORCE` — optional System-1 integration.

Provide service URLs explicitly through deployment environment variables. Store API keys and MCP credentials in secrets.

## Development
Python 3.12+; use uv.
```bash
uv sync --dev
uv run ruff check .
uv run mypy src
uv run pytest
```
Run through `ai-infra` so the model gateway and MCP services are available.

## Security
Configure only trusted MCP servers with least-privilege credentials. Keep the service internal, bound tool execution with timeouts, preserve trace IDs, and treat model/tool outputs as untrusted. Laya is an optional decision aid, not a replacement for authorization or deterministic controls.
