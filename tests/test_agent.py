import json
import pytest
from agent_core.agent import Agent
from agent_core.config import Settings

class FakeFunction:
    name = "echo"
    arguments = json.dumps({"text": "hello"})

class FakeCall:
    id = "call-1"
    type = "function"
    function = FakeFunction()

class FakeMessage:
    content = "done"
    tool_calls = None
    def model_dump(self, exclude_none=True):
        return {"role": "assistant", "content": self.content}

class ToolMessage(FakeMessage):
    tool_calls = [FakeCall()]
    content = None

class FakeChoice:
    def __init__(self, message): self.message = message

class FakeResponse:
    def __init__(self, message): self.choices = [FakeChoice(message)]

class FakeCompletions:
    def __init__(self): self.calls = 0
    async def create(self, **kwargs):
        self.calls += 1
        return FakeResponse(ToolMessage() if self.calls == 1 else FakeMessage())

class FakeClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeCompletions()})()

class FakeRegistry:
    async def list_tools(self):
        attrs = {"name": "echo", "description": "echo", "input_schema": {"type": "object"}, "server": "test"}
        tool = type("Tool", (), attrs)
        return [tool()]
    async def call(self, server, name, arguments):
        assert (server, name, arguments) == ("test", "echo", {"text": "hello"})
        return {"ok": True}

@pytest.mark.asyncio
async def test_agent_executes_tool_then_returns_answer():
    agent = Agent(Settings(max_iterations=3), FakeRegistry())
    agent.client = FakeClient()
    result = await agent.run("hello")
    assert result == ("done", 2, 1)

@pytest.mark.asyncio
async def test_agent_iteration_limit():
    class Endless(FakeClient):
        def __init__(self):
            super().__init__()
            self.chat.completions = type("C", (), {"create": self.create})()
        async def create(self, **kwargs):
            return FakeResponse(ToolMessage())
    agent = Agent(Settings(max_iterations=1), FakeRegistry())
    agent.client = Endless()
    with pytest.raises(RuntimeError, match="iteration"):
        await agent.run("hello")
