from fastapi.testclient import TestClient
from agent_core.api import app

def test_health():
    assert TestClient(app).get("/health").json() == {"status": "ok"}

def test_chat_request_validation():
    response = TestClient(app).post("/v1/chat", json={"message": ""})
    assert response.status_code == 422
