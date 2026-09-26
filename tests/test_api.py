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
