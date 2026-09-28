import json

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
    payload = response.json()
    assert payload["answer"] == "The answer is supported [S1]."
    assert payload["citations"] == [
        {"id": "S1", "chunk_id": "c1", "source_name": "mailbox", "text": "Evidence text"}
    ]
    assert payload["iterations"] == 2
    assert payload["tool_calls"] == 1
    assert payload["trace"]["schema_version"] == "1.0"
    assert payload["trace"]["status"] == "completed"
    assert payload["trace"]["trace_id"]


def test_grounded_answer_stream_contract(monkeypatch):
    import agent_core.api as api
    from agent_core.agent import CitationEvidence, current_trace

    async def fake_stream(question=None, model=None, *, conversation_messages=None):
        trace = current_trace()
        assert trace is not None
        trace.log(level="INFO", message="stream delta emitted", stage="llm")
        trace.metric("stream_deltas", 2)
        event_id = trace.event(
            kind="llm",
            stage="llm",
            name="stream.iteration",
            payload={"content": "Hello world."},
        )
        trace.finish_event(event_id, status="completed")
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

    frames = [frame for frame in response.text.split("\n\n") if frame]
    assert len(frames) == 3
    assert frames[0].startswith("event: delta\ndata: ")
    assert frames[1].startswith("event: delta\ndata: ")
    assert frames[2].startswith("event: done\ndata: ")

    delta_payloads = [json.loads(frame.split("data: ", 1)[1]) for frame in frames[:2]]
    assert delta_payloads == [{"content": "Hello "}, {"content": "world."}]

    done = json.loads(frames[2].split("data: ", 1)[1])
    assert done["citations"] == [
        {"id": "S1", "chunk_id": "c1", "source_name": "mailbox", "text": "Evidence"}
    ]
    assert done["iterations"] == 2
    assert done["tool_calls"] == 1
    assert done["trace_id"]
    assert done["trace"]["trace_id"] == done["trace_id"]
    assert done["trace"]["status"] == "completed"
    assert len(done["trace"]["logs"]) == 1
    assert done["trace"]["logs"][0]["level"] == "INFO"
    assert done["trace"]["logs"][0]["message"] == "stream delta emitted"
    assert done["trace"]["logs"][0]["stage"] == "llm"
    assert done["trace"]["metrics"]["stream_deltas"] == 2
    assert len(done["trace"]["trace"]) == 1
    assert done["trace"]["trace"][0]["name"] == "stream.iteration"
    assert done["trace"]["trace"][0]["status"] == "completed"


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


def test_request_id_is_returned():
    response = TestClient(app).get("/api/v1/health", headers={"X-Request-ID": "phase1c-test-id"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "phase1c-test-id"


def test_grounded_answer_maps_agent_failure_to_502(monkeypatch):
    import agent_core.api as api

    async def failing_answer(question=None, model=None, *, messages=None):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(api.agent, "run_grounded_answer", failing_answer)
    response = TestClient(app).post("/api/v1/answer", json={"question": "What?"})
    assert response.status_code == 502
    assert response.json()["detail"] == "grounded answer dependency failed"


def test_grounded_answer_stream_maps_tool_validation_failure_to_error_event(monkeypatch):
    import agent_core.api as api
    from agent_core.mcp_client import MCPToolArgumentError
    from agent_core.observability import current_trace

    async def failing_stream(question=None, model=None, *, conversation_messages=None):
        trace = current_trace()
        assert trace is not None
        event_id = trace.event(
            kind="tool",
            stage="tool",
            name="web.echo",
            payload={"arguments": {"text": 123}},
        )
        trace.finish_event(
            event_id,
            status="failed",
            payload={"error": {"type": "MCPToolArgumentError", "message": "invalid arguments"}},
        )
        yield {"type": "delta", "content": "partial"}
        raise MCPToolArgumentError("invalid arguments for tool web.echo: text: 123 is not of type 'string'")

    monkeypatch.setattr(api.agent, "stream_grounded_answer", failing_stream)
    response = TestClient(app).post("/api/v1/answer/stream", json={"question": "What?"})
    assert response.status_code == 200

    frames = [frame for frame in response.text.split("\n\n") if frame]
    assert len(frames) == 1
    assert frames[0].startswith("event: error\ndata: ")

    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert payload["detail"] == "grounded answer dependency failed"
    assert payload["trace_id"]
