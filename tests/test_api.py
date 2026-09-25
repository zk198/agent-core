from fastapi.testclient import TestClient

from agent_core.api import app


def test_health():
    assert TestClient(app).get("/healthz").json() == {"status": "ok"}


def test_chat_request_validation():
    response = TestClient(app).post("/chat", json={"message": ""})
    assert response.status_code == 422


def test_health_is_local():
    response = TestClient(app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
