import pytest

from agent_core.config import Settings


def test_default_mcp_servers_include_rag_gateway():
    settings = Settings()
    assert "rag-gateway:8001/mcp" in settings.mcp_servers


def test_mcp_auth_tokens_must_align():
    with pytest.raises(ValueError):
        Settings(mcp_servers="a,b", mcp_auth_tokens="token")
