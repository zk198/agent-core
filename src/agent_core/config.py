from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .mcp_client import MCPServer


class Settings(BaseSettings):
    model_base_url: str = "http://llm-gateway:8080/v1"
    model_api_key: str = "local"
    model_name: str = "local/default"
    model_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    max_iterations: int = Field(default=8, ge=1, le=32)
    max_tool_calls: int = Field(default=16, ge=1, le=64)
    max_tool_result_chars: int = Field(default=20_000, ge=1, le=200_000)
    context_reserve_chars: int = Field(default=4_000, ge=0, le=100_000)
    mcp_servers: str = (
        "http://agent-tools-web:8001/mcp,"
        "http://agent-tools-code:8001/mcp,"
        "http://rag-gateway:8200/mcp"
    )
    mcp_auth_tokens: str = ""
    mcp_server_names: str = "web,code,rag"

    model_config = SettingsConfigDict(env_prefix="AGENT_")

    def mcp_server_configs(self) -> list[MCPServer]:
        urls = [value.strip() for value in self.mcp_servers.split(",") if value.strip()]
        names = [value.strip() for value in self.mcp_server_names.split(",") if value.strip()]
        if len(names) != len(urls):
            raise ValueError("AGENT_MCP_SERVER_NAMES must match AGENT_MCP_SERVERS")
        if not all(names) or len(set(names)) != len(names):
            raise ValueError("AGENT_MCP_SERVER_NAMES must be unique and non-empty")

        raw_tokens = self.mcp_auth_tokens.strip()
        tokens = [] if not raw_tokens else [
            value.strip() for value in self.mcp_auth_tokens.split(",")
        ]
        if tokens and len(tokens) != len(urls):
            raise ValueError("AGENT_MCP_AUTH_TOKENS must match AGENT_MCP_SERVERS")

        return [
            MCPServer(
                url=url,
                auth_token=(tokens[index] or None) if tokens else None,
                name=names[index],
            )
            for index, url in enumerate(urls)
        ]
