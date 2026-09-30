import json

import pytest

from agent_core.agent import Agent
from agent_core.config import Settings
from agent_core.observability import start_trace, reset_trace


class DummyRegistry:
    pass


class FakeLaya:
    async def decide(self, state, questions):
        return {"answers": {"request_type": {"choice": "knowledge"}}, "routing": {"model": "english"}}


@pytest.mark.anyio
async def test_laya_decision_is_recorded_as_distinct_trace_event():
    settings = Settings(
        laya_enabled=True,
        laya_questions_json=json.dumps({
            "request_type": {
                "type": "choice",
                "instructions": "Classify the request type.",
                "criteria": {"knowledge": "information request", "other": "other"},
            }
        }),
    )
    agent = Agent(settings, DummyRegistry())
    agent.laya = FakeLaya()
    trace, token = start_trace()
    try:
        result = await agent._laya_decision([{"role": "user", "content": "What is RAG?"}])
        assert result is not None
        event = trace.events[-1]
        assert event["kind"] == "system1"
        assert event["stage"] == "laya"
        assert event["duration_ms"] is not None
        assert event["payload"]["answers"]["request_type"]["choice"] == "knowledge"
    finally:
        reset_trace(token)


@pytest.mark.anyio
async def test_laya_disabled_does_not_call_service():
    settings = Settings(laya_enabled=False, laya_questions_json="{}")
    agent = Agent(settings, DummyRegistry())

    class FailingLaya:
        async def decide(self, *_):
            raise AssertionError("disabled Laya must not be called")

    agent.laya = FailingLaya()
    assert await agent._laya_decision([{"role": "user", "content": "hello"}]) is None
