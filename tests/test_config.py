import pytest

from agent_core.config import Settings


def test_default_mcp_servers_include_rag_gateway():
    settings = Settings()
    assert "rag-gateway:8001/mcp" in settings.mcp_servers


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


def test_mcp_auth_tokens_must_align():
    settings = Settings(
        mcp_servers="a,b",
        mcp_auth_tokens="token",
        mcp_server_names="web,code",
    )
    with pytest.raises(ValueError, match="AGENT_MCP_AUTH_TOKENS"):
        settings.mcp_server_configs()
