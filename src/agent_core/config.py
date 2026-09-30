import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .mcp_client import MCPServer


class Settings(BaseSettings):
    # Service endpoints are deployment topology and must come from AGENT_* environment
    # variables. Docker Compose is the source of truth for those values.
    model_base_url: str = Field(default_factory=lambda: os.environ["AGENT_MODEL_BASE_URL"], min_length=1)
    model_api_key: str = "local"
    model_name: str = "local/default"
    model_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    max_iterations: int = Field(default=8, ge=1, le=32)
    max_tool_calls: int = Field(default=16, ge=1, le=64)
    max_tool_result_chars: int = Field(default=20_000, ge=1, le=200_000)
    context_reserve_chars: int = Field(default=4_000, ge=0, le=100_000)
    laya_enabled: bool = False
    laya_url: str = Field(default_factory=lambda: os.environ["AGENT_LAYA_URL"], min_length=1)
    laya_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    laya_api_key: str | None = None
    laya_questions_json: str = ""
    laya_enforce: bool = False
    mcp_servers: str = Field(default_factory=lambda: os.environ["AGENT_MCP_SERVERS"], min_length=1)
    mcp_auth_tokens: str = ""
    mcp_server_names: str = "web,code,rag"

    model_config = SettingsConfigDict(env_prefix="AGENT_")

    def mcp_server_configs(self) -> list[MCPServer]:
        urls = [value.strip() for value in self.mcp_servers.split(",")]
        names = [value.strip() for value in self.mcp_server_names.split(",")]
        if len(names) != len(urls):
            raise ValueError("AGENT_MCP_SERVER_NAMES must match AGENT_MCP_SERVERS")
        if not all(urls) or not all(names) or len(set(names)) != len(names):
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
