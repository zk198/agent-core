import httpx
import pytest

from agent_core.laya_client import LayaClient


@pytest.mark.anyio
async def test_laya_client_mock_success(monkeypatch):
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request_id"] = request.headers["X-Request-ID"]
        return httpx.Response(200, json={"answers": {"allowed": {"noul": True}}, "routing": {"model": "english"}})

    monkeypatch.setattr("agent_core.laya_client.request_id", lambda: "req-123")
    client = LayaClient("http://laya:8000", transport=httpx.MockTransport(handler))
    result = await client.decide("hello", {"allowed": {"type": "noul", "instructions": "Is this allowed?"}})
    assert result["answers"]["allowed"]["noul"] is True
    assert seen["request_id"] == "req-123"


@pytest.mark.anyio
async def test_laya_client_maps_timeout():
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    client = LayaClient("http://laya:8000", transport=httpx.MockTransport(handler))
    with pytest.raises(TimeoutError, match="laya timeout"):
        await client.decide("hello", {"allowed": {"type": "noul", "instructions": "Is this allowed?"}})
