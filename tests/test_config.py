import pytest

from agent_core.config import Settings


def test_service_urls_are_loaded_from_environment():
    settings = Settings()
    assert settings.model_base_url == "http://llm-gateway:8080/v1"
    assert settings.laya_url == "http://laya:8000"
    assert "ai-gateway:8200/mcp" in settings.mcp_servers


def test_default_empty_mcp_auth_tokens_are_allowed():
    settings = Settings(mcp_servers="a,b", mcp_server_names="web,code")
    configs = settings.mcp_server_configs()
    assert [(item.url, item.auth_token, item.name) for item in configs] == [
        ("a", None, "web"),
        ("b", None, "code"),
    ]


def test_mcp_auth_tokens_support_empty_slots():
    settings = Settings(
        mcp_servers="a,b",
        mcp_auth_tokens="token,",
        mcp_server_names="one,two",
    )
    configs = settings.mcp_server_configs()
    assert configs[0].url == "a"
    assert configs[0].auth_token == "token"
    assert configs[0].name == "one"
    assert configs[1].url == "b"
    assert configs[1].auth_token is None
    assert configs[1].name == "two"


def test_mcp_server_names_must_align():
    settings = Settings(mcp_servers="a,b", mcp_server_names="one")
    with pytest.raises(ValueError, match="AGENT_MCP_SERVER_NAMES"):
        settings.mcp_server_configs()


def test_mcp_server_names_must_be_unique_and_non_empty():
    duplicate = Settings(mcp_servers="a,b", mcp_server_names="web,web")
    with pytest.raises(ValueError, match="unique"):
        duplicate.mcp_server_configs()

    empty = Settings(mcp_servers="a,b", mcp_server_names="web,")
    with pytest.raises(ValueError, match="unique"):
        empty.mcp_server_configs()


def test_mcp_auth_tokens_must_align():
    settings = Settings(
        mcp_servers="a,b",
        mcp_auth_tokens="token",
        mcp_server_names="web,code",
    )
    with pytest.raises(ValueError, match="AGENT_MCP_AUTH_TOKENS"):
        settings.mcp_server_configs()
