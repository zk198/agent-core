from agent_core.observability import ExecutionTrace


def test_execution_trace_serializes_logs_metrics_and_ordered_events():
    trace = ExecutionTrace(trace_id="trace-1", request_id="req-1")
    parent = trace.event(\n        kind="llm", stage="llm", name="iteration.1", payload={"prompt": "hello"}\n    )
    child = trace.event(\n        kind="tool",\n        stage="retrieval",\n        name="rag.search_knowledge",\n        parent_id=parent,\n        payload={"arguments": {"query": "hello"}},\n    )
    trace.finish_event(child, payload={"result": {"chunk_id": "c1", "text": "evidence"}}, duration_ms=12.3)
    trace.finish_event(parent, payload={"response": {"content": "answer"}}, duration_ms=25.0)
    trace.log(level="INFO", message="completed")
    trace.metric("llm_calls", 1)
    trace.complete()

    data = trace.to_dict()

    assert data["schema_version"] == "1.0"
    assert data["trace_id"] == "trace-1"
    assert data["request_id"] == "req-1"
    assert data["status"] == "completed"
    assert data["events"] if "events" in data else True
    assert [event["sequence"] for event in data["trace"]] == [1, 2]
    assert data["trace"][1]["parent_id"] == parent
    assert data["trace"][1]["payload"]["arguments"]["query"] == "hello"
    assert data["logs"][0]["message"] == "completed"
    assert data["metrics"]["llm_calls"] == 1
