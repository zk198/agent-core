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


def test_answer_request_validation():
    response = TestClient(app).post("/api/v1/answer", json={"question": ""})
    assert response.status_code == 422


def test_grounded_answer_contract(monkeypatch):
    import agent_core.api as api
    from agent_core.agent import AgentResult, CitationEvidence

    async def fake_answer(question=None, model=None, *, messages=None):
        return AgentResult(
            content="The answer is supported [S1].",
            iterations=2,
            tool_calls=1,
            citations=(CitationEvidence("c1", "mailbox", "Evidence text"),),
        )

    monkeypatch.setattr(api.agent, "run_grounded_answer", fake_answer)
    response = TestClient(app).post("/api/v1/answer", json={"question": "What?"})
    assert response.status_code == 200
    assert response.json() == {
        "answer": "The answer is supported [S1].",
        "citations": [{"id": "S1", "chunk_id": "c1", "source_name": "mailbox", "text": "Evidence text"}],
        "iterations": 2,
        "tool_calls": 1,
    }


def test_grounded_answer_stream_contract(monkeypatch):
    import agent_core.api as api
    from agent_core.agent import CitationEvidence

    async def fake_stream(question=None, model=None, *, conversation_messages=None):
        yield {"type": "delta", "content": "Hello "}
        yield {"type": "delta", "content": "world."}
        yield {
            "type": "done",
            "citations": [CitationEvidence("c1", "mailbox", "Evidence")],
            "iterations": 2,
            "tool_calls": 1,
        }

    monkeypatch.setattr(api.agent, "stream_grounded_answer", fake_stream)
    response = TestClient(app).post("/api/v1/answer/stream", json={"question": "What?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: delta" in response.text
    assert '"content": "Hello "' in response.text
    assert "event: done" in response.text
    assert '"id": "S1"' in response.text


def test_chat_accepts_message_history(monkeypatch):
    import agent_core.api as api

    async def fake_run_messages(messages, model=None):
        assert messages == [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "previous"},
            {"role": "user", "content": "second"},
        ]
        return "ok", 1, 0

    monkeypatch.setattr(api.agent, "run_messages", fake_run_messages)
    response = TestClient(app).post(
        "/api/v1/chat",
        json={"messages": [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "previous"},
            {"role": "user", "content": "second"},
        ]},
    )
    assert response.status_code == 200
    assert response.json()["content"] == "ok"


def test_chat_requires_message_or_messages():
    response = TestClient(app).post("/api/v1/chat", json={})
    assert response.status_code == 422


def test_grounded_answer_accepts_message_history(monkeypatch):
    import agent_core.api as api
    from agent_core.agent import AgentResult

    async def fake_answer(question=None, model=None, *, messages=None):
        assert messages == [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "previous"},
            {"role": "user", "content": "second"},
        ]
        return AgentResult(content="grounded", iterations=1, tool_calls=1)

    monkeypatch.setattr(api.agent, "run_grounded_answer", fake_answer)
    response = TestClient(app).post(
        "/api/v1/answer",
        json={"messages": [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "previous"},
            {"role": "user", "content": "second"},
        ]},
    )
    assert response.status_code == 200
    assert response.json()["answer"] == "grounded"
