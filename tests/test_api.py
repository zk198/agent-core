from fastapi.testclient import TestClient

from agent_core.api import app


def test_health():
    response = TestClient(app).get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_request_validation():
    response = TestClient(app).post("/api/v1/chat", json={"message": ""})
    assert response.status_code == 422


def test_health_is_local():
    response = TestClient(app).get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_tool_info_contract(monkeypatch):
    import agent_core.api as api

    class Tool:
        name = "echo"
        qualified_name = "web.echo"
        model_name = "web__echo"
        description = "Echo"

    async def fake_list_tools():
        return [Tool()]

    monkeypatch.setattr(api.registry, "list_tools", fake_list_tools)
    response = TestClient(app).get("/api/v1/tools")

    assert response.status_code == 200
    assert response.json() == [
        {
            "name": "echo",
            "qualified_name": "web.echo",
            "model_name": "web__echo",
            "description": "Echo",
        }
    ]


def test_ready_reports_dependency_failure(monkeypatch):
    import agent_core.api as api

    async def failing_list_tools():
        raise RuntimeError("MCP unavailable")

    monkeypatch.setattr(api.registry, "list_tools", failing_list_tools)
    response = TestClient(app).get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == "MCP dependencies unavailable"
