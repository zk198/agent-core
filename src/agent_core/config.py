from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_base_url: str = "http://llm-gateway:8080/v1"
    model_api_key: str = "local"
    model_name: str = "local/default"
    max_iterations: int = 8
    max_tool_result_chars: int = 20_000
    mcp_servers: str = "http://agent-tools-web:8001/mcp,http://agent-tools-code:8001/mcp"
    model_config = SettingsConfigDict(env_prefix="AGENT_")
