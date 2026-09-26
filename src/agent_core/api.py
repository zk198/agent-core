import logging
import time

from fastapi import FastAPI, HTTPException, Request

from .agent import Agent
from .config import Settings
from .mcp_client import MCPRegistry
from .models import ChatRequest, ChatResponse, ToolInfo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent_core")

settings = Settings()
registry = MCPRegistry(settings.mcp_server_configs())
agent = Agent(settings, registry)

app = FastAPI(title="Agent Core", version="0.2.0")


@app.middleware("http")
async def request_logging(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request_failed method=%s path=%s", request.method, request.url.path)
        raise
    logger.info(
        "request method=%s path=%s status=%s duration_ms=%.1f",
        request.method,
        request.url.path,
        response.status_code,
        (time.perf_counter() - started) * 1000,
    )
    return response


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/ready")
async def ready() -> dict[str, str]:
    try:
        await registry.list_tools()
    except Exception as exc:
        logger.warning("readiness_failed error=%s", exc)
        raise HTTPException(status_code=503, detail="MCP dependencies unavailable") from exc
    return {"status": "ready"}


@app.get("/api/v1/tools")
async def tools() -> list[ToolInfo]:
    discovered = await registry.list_tools()
    return [
        ToolInfo(
            name=tool.name,
            qualified_name=tool.qualified_name,
            model_name=tool.model_name,
            description=tool.description,
        )
        for tool in discovered
    ]


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    try:
        content, iterations, tool_calls = await agent.run(request.message, request.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("agent_run_failed")
        raise HTTPException(status_code=502, detail="agent dependency failed") from exc
    return ChatResponse(content=content, iterations=iterations, tool_calls=tool_calls)
