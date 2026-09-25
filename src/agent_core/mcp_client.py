from dataclasses import dataclass
from typing import Any
from fastmcp import Client

@dataclass(frozen=True)
class MCPTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    server: str

class MCPRegistry:
    def __init__(self, servers: list[str]) -> None:
        self.servers = servers

    async def list_tools(self) -> list[MCPTool]:
        result: list[MCPTool] = []
        for url in self.servers:
            async with Client(url) as client:
                for tool in await client.list_tools():
                    result.append(MCPTool(
                        name=tool.name,
                        description=tool.description or "",
                        input_schema=tool.inputSchema,
                        server=url,
                    ))
        return result

    async def call(self, server: str, name: str, arguments: dict[str, Any]) -> Any:
        async with Client(server) as client:
            return await client.call_tool(name, arguments)
