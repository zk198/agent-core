from fastapi import FastAPI

from .agent import Agent
from .config import Settings
from .mcp_client import MCPRegistry
from .models import ChatRequest, ChatResponse, ToolInfo

settings = Settings()
registry = MCPRegistry(settings.mcp_server_configs())
agent = Agent(settings, registry)

app = FastAPI(title="Agent Core")


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/tools")
async def tools() -> list[ToolInfo]:
    discovered = await registry.list_tools()
    return [ToolInfo(name=tool.name, description=tool.description) for tool in discovered]


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    content, iterations, tool_calls = await agent.run(request.message, request.model)
    return ChatResponse(content=content, iterations=iterations, tool_calls=tool_calls)
