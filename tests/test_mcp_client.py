import pytest
from agent_core.mcp_client import MCPRegistry

class FakeTool:
    name = "echo"
    description = "Echo"
    inputSchema = {"type": "object"}

class FakeClient:
    def __init__(self, url):
        self.url = url
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        return None
    async def list_tools(self):
        return [FakeTool()]
    async def call_tool(self, name, arguments):
        return {"name": name, "arguments": arguments}

@pytest.mark.asyncio
async def test_registry_lists_and_calls_mcp(monkeypatch):
    import agent_core.mcp_client as module
    monkeypatch.setattr(module, "Client", FakeClient)
    registry = MCPRegistry(["http://tools/mcp"])
    tools = await registry.list_tools()
    assert tools[0].name == "echo"
    assert await registry.call("http://tools/mcp", "echo", {"x": 1}) == {"name": "echo", "arguments": {"x": 1}}
