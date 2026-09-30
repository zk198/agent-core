import os


os.environ.setdefault("AGENT_MODEL_BASE_URL", "http://llm-gateway:8080/v1")
os.environ.setdefault("AGENT_LAYA_URL", "http://laya:8000")
os.environ.setdefault(
    "AGENT_MCP_SERVERS",
    "http://agent-tools-web:8001/mcp,http://agent-tools-code:8001/mcp,http://ai-gateway:8200/mcp/",
)
