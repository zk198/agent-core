import json

import pytest

from agent_core.agent import Agent
from agent_core.config import Settings


class FakeFunction:
    name = "web__echo"
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
    def __init__(self, message):
        self.message = message


class FakeResponse:
    def __init__(self, message):
        self.choices = [FakeChoice(message)]


class FakeCompletions:
    def __init__(self):
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        return FakeResponse(ToolMessage() if self.calls == 1 else FakeMessage())


class FakeClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeCompletions()})()


class FakeRegistry:
    async def list_tools(self):
        attrs = {
            "name": "echo",
            "description": "echo",
            "input_schema": {"type": "object"},
            "server": "test",
            "server_name": "web",
            "model_name": "web__echo",
        }
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
async def test_agent_rejects_malformed_tool_arguments():
    class BadArgs(FakeClient):
        def __init__(self):
            super().__init__()

            class BadFunction:
                name = "web__echo"
                arguments = "["

            class BadCall:
                id = "call-bad"
                type = "function"
                function = BadFunction()

            class BadToolMessage(FakeMessage):
                tool_calls = [BadCall()]
                content = None

            async def create(_self, **kwargs):
                return FakeResponse(BadToolMessage())

            self.chat.completions = type("C", (), {"create": create})()

    agent = Agent(Settings(max_iterations=3), FakeRegistry())
    agent.client = BadArgs()
    with pytest.raises(RuntimeError, match="invalid arguments"):
        await agent.run("hello")


@pytest.mark.asyncio
async def test_agent_enforces_tool_call_limit():
    class Endless(FakeClient):
        def __init__(self):
            super().__init__()
            self.chat.completions = type("C", (), {"create": self.create})()

        async def create(self, **kwargs):
            return FakeResponse(ToolMessage())

    agent = Agent(Settings(max_iterations=32, max_tool_calls=1), FakeRegistry())
    agent.client = Endless()
    with pytest.raises(RuntimeError, match="tool call limit"):
        await agent.run("hello")


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


class RagRegistry(FakeRegistry):
    async def list_tools(self):
        attrs = {
            "name": "search_knowledge",
            "description": "search RAG",
            "input_schema": {"type": "object"},
            "server": "rag",
            "server_name": "rag",
            "model_name": "rag__search_knowledge",
        }
        tool = type("Tool", (), attrs)
        return [tool()]

    async def call(self, server, name, arguments):
        assert (server, name) == ("rag", "search_knowledge")
        return [{
            "chunk_id": "c1",
            "source_name": "mailbox",
            "text": "The project marker is RAG_E2E_MARKER.",
        }]


class RagFunction:
    name = "rag__search_knowledge"
    arguments = json.dumps({"query": "marker"})


class RagCall:
    id = "rag-call"
    type = "function"
    function = RagFunction()


@pytest.mark.asyncio
async def test_grounded_answer_filters_to_rag_and_collects_citations():
    class GroundedClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.seen_messages = []

        async def create(self, **kwargs):
            self.seen_messages.append(kwargs["messages"])
            if len(self.seen_messages) == 1:
                message = ToolMessage()
                message.tool_calls = [RagCall()]
                return FakeResponse(message)
            return FakeResponse(FakeMessage())

    agent = Agent(Settings(max_iterations=3), RagRegistry())
    agent.client = GroundedClient()
    result = await agent.run_grounded_answer("What is the marker?")
    assert result.content == "done"
    assert result.tool_calls == 1
    assert result.citations[0].chunk_id == "c1"
    assert result.citations[0].source_name == "mailbox"
    assert result.citations[0].text == "The project marker is RAG_E2E_MARKER."


@pytest.mark.asyncio
async def test_grounded_answer_injects_citation_instructions():
    class GroundedClient(FakeClient):
        async def create(self, **kwargs):
            assert kwargs["messages"][0]["role"] == "system"
            assert "only evidence returned by the RAG tools" in kwargs["messages"][0]["content"]
            return FakeResponse(FakeMessage())

    agent = Agent(Settings(max_iterations=1), RagRegistry())
    agent.client = GroundedClient()
    result = await agent.run_grounded_answer("Question")
    assert result.content == "done"
