import json
from typing import Any
from openai import AsyncOpenAI
from .config import Settings
from .mcp_client import MCPRegistry

class Agent:
    def __init__(self, settings: Settings, registry: MCPRegistry) -> None:
        self.settings = settings
        self.registry = registry
        self.client = AsyncOpenAI(base_url=settings.model_base_url, api_key=settings.model_api_key)

    async def run(self, message: str, model: str | None = None) -> tuple[str, int, int]:
        tools = await self.registry.list_tools()
        openai_tools: list[Any] = [{"type": "function", "function": {
            "name": t.name, "description": t.description, "parameters": t.input_schema
        }} for t in tools]
        messages: list[Any] = [{"role": "user", "content": message}]
        tool_calls_total = 0
        for iteration in range(1, self.settings.max_iterations + 1):
            response = await self.client.chat.completions.create(
                model=model or self.settings.model_name,
                messages=messages,
                tools=openai_tools or None,
            )
            choice = response.choices[0]
            if not choice.message.tool_calls:
                return choice.message.content or "", iteration, tool_calls_total
            messages.append(choice.message.model_dump(exclude_none=True))
            for call in choice.message.tool_calls:
                if getattr(call, "type", None) != "function":
                    continue
                function = getattr(call, "function", None)
                if function is None:
                    continue
                tool_calls_total += 1
                if tool_calls_total > self.settings.max_iterations * 2:
                    raise RuntimeError("tool call limit exceeded")
                target = next((t for t in tools if t.name == function.name), None)
                if target is None:
                    raise RuntimeError(f"unknown tool: {call.function.name}")
                args = json.loads(function.arguments or "{}")
                result = await self.registry.call(target.server, target.name, args)
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": str(result)[:self.settings.max_tool_result_chars]})
        raise RuntimeError("agent iteration limit exceeded")
