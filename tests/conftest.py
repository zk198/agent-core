import os


os.environ.setdefault("AGENT_MODEL_BASE_URL", "http://model.invalid/v1")
os.environ.setdefault("AGENT_LAYA_URL", "http://laya.invalid")
os.environ.setdefault(
    "AGENT_MCP_SERVERS",
    "http://web.invalid/mcp,http://code.invalid/mcp,http://rag.invalid/mcp/",
)
