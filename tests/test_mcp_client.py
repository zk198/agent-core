from fastmcp import FastMCP
from fastmcp.client import Client

import pytest

from agent_core.mcp_client import MCPRegistry, MCPServer


@pytest.mark.asyncio
async def test_list_tools_is_namespaced_and_uses_current_schema_field():
    server = FastMCP("test")

    @server.tool
    def echo(text: str) -> str:
        """Echo text."""
        return text

    registry = MCPRegistry([MCPServer("test://local", name="web")])
    registry._client = lambda _: Client(server)  # type: ignore[method-assign]
    tools = await registry.list_tools()

    assert [tool.name for tool in tools] == ["echo"]
    assert tools[0].qualified_name == "web.echo"
    assert tools[0].model_name == "web__echo"


@pytest.mark.asyncio
async def test_duplicate_tool_names_are_distinct_across_servers():
    web_server = FastMCP("web")
    code_server = FastMCP("code")

    @web_server.tool(name="echo")
    def web_echo(text: str) -> str:
        """Web echo."""
        return f"web:{text}"

    @code_server.tool
    def echo(text: str) -> str:
        """Code echo."""
        return f"code:{text}"

    servers = [
        MCPServer("test://web", name="web"),
        MCPServer("test://code", name="code"),
    ]
    registry = MCPRegistry(servers)

    clients = {
        "test://web": Client(web_server),
        "test://code": Client(code_server),
    }
    registry._client = lambda server: clients[server.url]  # type: ignore[method-assign]

    tools = await registry.list_tools()

    assert {tool.qualified_name for tool in tools} == {"web.echo", "code.echo"}
    assert {tool.model_name for tool in tools} == {"web__echo", "code__echo"}


@pytest.mark.asyncio
async def test_call_uses_raw_mcp_tool_name_after_model_namespace_resolution():
    server = FastMCP("web")

    @server.tool
    def echo(text: str) -> str:
        """Echo text."""
        return f"web:{text}"

    mcp_server = MCPServer("test://web", name="web")
    registry = MCPRegistry([mcp_server])
    registry._client = lambda _: Client(server)  # type: ignore[method-assign]

    tools = await registry.list_tools()
    target = next(tool for tool in tools if tool.model_name == "web__echo")
    result = await registry.call(target.server, target.name, {"text": "hello"})

    assert result.content[0].text == "web:hello"


@pytest.mark.asyncio
async def test_auth_client_factory():
    server = MCPServer("https://example.test/mcp", "secret", name="rag")
    registry = MCPRegistry([server])
    client = registry._client(server)
    assert client is not None
