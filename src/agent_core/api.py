from fastapi import FastAPI
from .agent import Agent
from .config import Settings
from .mcp_client import MCPRegistry
from .models import ChatRequest, ChatResponse, ToolInfo

settings = Settings()
registry = MCPRegistry([x.strip() for x in settings.mcp_servers.split(",") if x.strip()])
agent = Agent(settings, registry)
app = FastAPI(title="Agent Core", version="0.1.0")

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/v1/tools", response_model=list[ToolInfo])
async def tools() -> list[ToolInfo]:
    return [ToolInfo(name=t.name, description=t.description) for t in await registry.list_tools()]

@app.post("/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    content, iterations, tool_calls = await agent.run(request.message, request.model)
    return ChatResponse(content=content, iterations=iterations, tool_calls=tool_calls)
