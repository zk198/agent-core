import pytest

from agent_core.config import Settings


def test_default_mcp_servers_include_rag_gateway():
    settings = Settings()
    assert "rag-gateway:8001/mcp" in settings.mcp_servers


def test_default_empty_mcp_auth_tokens_are_allowed():
    settings = Settings(mcp_servers="a,b")
    configs = settings.mcp_server_configs()
    assert [(item.url, item.auth_token) for item in configs] == [
        ("a", None),
        ("b", None),
    ]


def test_mcp_auth_tokens_support_empty_slots():
    settings = Settings(mcp_servers="a,b", mcp_auth_tokens="token,")
    configs = settings.mcp_server_configs()
    assert configs[0].url == "a"
    assert configs[0].auth_token == "token"
    assert configs[1].url == "b"
    assert configs[1].auth_token is None


def test_mcp_auth_tokens_must_align():
    with pytest.raises(ValueError):
        Settings(mcp_servers="a,b", mcp_auth_tokens="token")
