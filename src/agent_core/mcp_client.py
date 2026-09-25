from dataclasses import dataclass
from typing import Any

from fastmcp import Client
from fastmcp.client.auth import BearerAuth


@dataclass(frozen=True)
class MCPServer:
    url: str
    auth_token: str | None = None


@dataclass(frozen=True)
class MCPTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    server: str


class MCPRegistry:
    def __init__(self, servers: list[MCPServer | str]) -> None:
        self.servers = [
            server if isinstance(server, MCPServer) else MCPServer(server)
            for server in servers
        ]

    def _client(self, server: MCPServer) -> Client:
        if server.auth_token:
            return Client(server.url, auth=BearerAuth(server.auth_token))
        return Client(server.url)

    async def list_tools(self) -> list[MCPTool]:
        result: list[MCPTool] = []
        for server in self.servers:
            async with self._client(server) as client:
                for tool in await client.list_tools():
                    result.append(
                        MCPTool(
                            name=tool.name,
                            description=tool.description or "",
                            input_schema=tool.inputSchema,
                            server=server.url,
                        )
                    )
        return result

    async def call(self, server: str, name: str, arguments: dict[str, Any]) -> Any:
        target = next((item for item in self.servers if item.url == server), None)
        if target is None:
            raise RuntimeError(f"unknown MCP server: {server}")
        async with self._client(target) as client:
            return await client.call_tool(name, arguments)
