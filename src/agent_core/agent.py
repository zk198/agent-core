import json
import logging
from typing import Any, cast

from openai import AsyncOpenAI

from .config import Settings
from .context import ContextBudget
from .mcp_client import MCPRegistry

logger = logging.getLogger(__name__)


class Agent:
    def __init__(self, settings: Settings, registry: MCPRegistry) -> None:
        self.settings = settings
        self.registry = registry
        self.client = AsyncOpenAI(
            base_url=settings.model_base_url,
            api_key=settings.model_api_key,
            timeout=settings.model_timeout_seconds,
        )

    async def run(self, message: str, model: str | None = None) -> tuple[str, int, int]:
        tools = await self.registry.list_tools()
        model_names = [tool.model_name for tool in tools]
        if len(model_names) != len(set(model_names)):
            raise RuntimeError("duplicate model-facing MCP tool names")

        openai_tools: list[Any] = [
            {
                "type": "function",
                "function": {
                    "name": tool.model_name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in tools
        ]
        messages: list[Any] = [{"role": "user", "content": message}]
        tool_calls_total = 0

        for iteration in range(1, self.settings.max_iterations + 1):
            logger.info(
                "agent iteration=%d tool_count=%d tool_calls=%d",
                iteration,
                len(tools),
                tool_calls_total,
            )
            response = await self.client.chat.completions.create(
                model=model or self.settings.model_name,
                messages=messages,
                tools=cast(Any, openai_tools or None),
            )
            if not response.choices:
                raise RuntimeError("model returned no choices")

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
                if tool_calls_total > self.settings.max_tool_calls:
                    raise RuntimeError("tool call limit exceeded")

                target = next(
                    (tool for tool in tools if tool.model_name == function.name),
                    None,
                )
                if target is None:
                    raise RuntimeError(f"unknown tool: {function.name}")

                try:
                    args = json.loads(function.arguments or "{}")
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"invalid arguments for tool {function.name}") from exc
                if not isinstance(args, dict):
                    raise RuntimeError(f"tool arguments for {function.name} must be an object")

                logger.info(
                    "agent tool_call=%s server=%s raw_tool=%s",
                    target.model_name,
                    target.server_name,
                    target.name,
                )
                result = await self.registry.call(target.server, target.name, args)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": ContextBudget(
                            self.settings.max_tool_result_chars,
                            self.settings.context_reserve_chars,
                        ).bound(result),
                    }
                )

        raise RuntimeError("agent iteration limit exceeded")
