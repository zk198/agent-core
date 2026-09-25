from fastmcp import FastMCP
from fastmcp.client import Client

import pytest

from agent_core.mcp_client import MCPRegistry, MCPServer


@pytest.mark.asyncio
async def test_list_tools():
    server = FastMCP("test")

    @server.tool
    def echo(text: str) -> str:
        """Echo text."""
        return text

    registry = MCPRegistry(["test://local"])
    registry._client = lambda _: Client(server)  # type: ignore[method-assign]
    tools = await registry.list_tools()
    assert [tool.name for tool in tools] == ["echo"]


@pytest.mark.asyncio
async def test_auth_client_factory():
    server = MCPServer("https://example.test/mcp", "secret")
    registry = MCPRegistry([server])
    client = registry._client(server)
    assert client is not None
