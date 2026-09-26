from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fastmcp import Client
from fastmcp.client.auth import BearerAuth
from fastmcp.client.transports import StreamableHttpTransport


@dataclass(frozen=True)
class MCPServer:
    url: str
    auth_token: str | None = None
    name: str | None = None

    @property
    def tool_namespace(self) -> str:
        if self.name:
            return self.name
        return self.url.rstrip("/").rsplit("/", 1)[-1] or "mcp"


@dataclass(frozen=True)
class MCPTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    server: str
    server_name: str

    @property
    def qualified_name(self) -> str:
        return f"{self.server_name}.{self.name}"

    @property
    def model_name(self) -> str:
        return f"{self.server_name}__{self.name}"


class MCPRegistry:
    def __init__(self, servers: Sequence[MCPServer | str]) -> None:
        self.servers = [
            server if isinstance(server, MCPServer) else MCPServer(server)
            for server in servers
        ]
        names = [server.tool_namespace for server in self.servers]
        if len(names) != len(set(names)):
            raise ValueError("MCP server names must be unique")

    def _client(self, server: MCPServer) -> Client:
        auth = BearerAuth(server.auth_token) if server.auth_token else None
        transport = StreamableHttpTransport(server.url, auth=auth)
        return Client(transport)

    async def list_tools(self) -> list[MCPTool]:
        result: list[MCPTool] = []
        for server in self.servers:
            async with self._client(server) as client:
                for tool in await client.list_tools():
                    result.append(
                        MCPTool(
                            name=tool.name,
                            description=tool.description or "",
                            input_schema=tool.input_schema,
                            server=server.url,
                            server_name=server.tool_namespace,
                        )
                    )
        model_names = [tool.model_name for tool in result]
        if len(model_names) != len(set(model_names)):
            raise RuntimeError("MCP tool aliases collide across configured servers")
        return result

    async def call(self, server: str, name: str, arguments: dict[str, Any]) -> Any:
        target = next((item for item in self.servers if item.url == server), None)
        if target is None:
            raise RuntimeError(f"unknown MCP server: {server}")
        async with self._client(target) as client:
            return await client.call_tool(name, arguments)
