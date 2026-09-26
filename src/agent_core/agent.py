import json
import logging
from dataclasses import dataclass
from typing import Any, cast

from openai import AsyncOpenAI

from .config import Settings
from .context import ContextBudget
from .mcp_client import MCPRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CitationEvidence:
    chunk_id: str
    source_name: str
    text: str


@dataclass(frozen=True)
class AgentResult:
    content: str
    iterations: int
    tool_calls: int
    citations: tuple[CitationEvidence, ...] = ()


def _structured_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_structured_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _structured_value(item) for key, item in value.items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _structured_value(model_dump())
        except Exception:
            pass
    text = getattr(value, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(value, "content", None)
    if content is not None:
        return _structured_value(content)
    return str(value)


def _result_text(value: Any) -> str:
    structured = _structured_value(value)
    if isinstance(structured, str):
        return structured
    return json.dumps(structured, ensure_ascii=False, default=str)


def _extract_rag_evidence(value: Any) -> list[CitationEvidence]:
    structured = _structured_value(value)
    if isinstance(structured, str):
        try:
            structured = json.loads(structured)
        except json.JSONDecodeError:
            return []
    if isinstance(structured, dict):
        candidates = structured.get("results", structured.get("data", []))
    else:
        candidates = structured
    if not isinstance(candidates, list):
        return []
    evidence: list[CitationEvidence] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        chunk_id = item.get("chunk_id")
        text = item.get("text")
        source_name = item.get("source_name")
        if isinstance(chunk_id, str) and isinstance(text, str) and isinstance(source_name, str):
            evidence.append(CitationEvidence(chunk_id=chunk_id, source_name=source_name, text=text))
    return evidence


class Agent:
    def __init__(self, settings: Settings, registry: MCPRegistry) -> None:
        self.settings = settings
        self.registry = registry
        self.client = AsyncOpenAI(
            base_url=settings.model_base_url,
            api_key=settings.model_api_key,
            timeout=settings.model_timeout_seconds,
        )

    async def run(
        self,
        message: str,
        model: str | None = None,
        *,
        system_prompt: str | None = None,
        allowed_server_names: set[str] | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> tuple[str, int, int]:
        result = await self._run(
            message,
            model,
            system_prompt=system_prompt,
            allowed_server_names=allowed_server_names,
            history=history,
        )
        return result.content, result.iterations, result.tool_calls

    async def run_grounded_answer(self, question: str, model: str | None = None, history: list[dict[str, str]] | None = None) -> AgentResult:
        return await self._run(
            question,
            model,
            system_prompt=(
                "You are a grounded knowledge assistant. Answer using only evidence returned "
                "by the RAG tools. Cite factual claims with the supplied citation IDs such as [S1]. "
                "Do not invent citations or facts. If the evidence is insufficient, say so explicitly."
            ),
            allowed_server_names={"rag"},
            collect_citations=True,
            history=history,
        )

    async def stream_grounded_answer(self, question: str, model: str | None = None, history: list[dict[str, str]] | None = None):
        system_prompt = (
            "You are a grounded knowledge assistant. Answer using only evidence returned "
            "by the RAG tools. Cite factual claims with the supplied citation IDs such as [S1]. "
            "Do not invent citations or facts. If the evidence is insufficient, say so explicitly."
        )
        tools = [tool for tool in await self.registry.list_tools() if tool.server_name == "rag"]
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
        messages: list[Any] = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(ContextBudget(self.settings.max_tool_result_chars, self.settings.context_reserve_chars).bound_messages(history))
        messages.append({"role": "user", "content": question})
        evidence: list[CitationEvidence] = []
        tool_calls_total = 0

        for iteration in range(1, self.settings.max_iterations + 1):
            stream = await self.client.chat.completions.create(
                model=model or self.settings.model_name,
                messages=messages,
                tools=cast(Any, openai_tools or None),
                stream=True,
            )
            content_parts: list[str] = []
            tool_calls: dict[int, dict[str, Any]] = {}
            async for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta.content:
                    content_parts.append(delta.content)
                    yield {"type": "delta", "content": delta.content}
                for tool_call in delta.tool_calls or []:
                    current = tool_calls.setdefault(
                        tool_call.index,
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    if tool_call.id:
                        current["id"] = tool_call.id
                    if tool_call.type:
                        current["type"] = tool_call.type
                    if tool_call.function:
                        if tool_call.function.name:
                            current["function"]["name"] = tool_call.function.name
                        if tool_call.function.arguments:
                            current["function"]["arguments"] += tool_call.function.arguments

            if not tool_calls:
                yield {
                    "type": "done",
                    "citations": evidence,
                    "iterations": iteration,
                    "tool_calls": tool_calls_total,
                }
                return

            assistant_tool_calls = [tool_calls[index] for index in sorted(tool_calls)]
            messages.append({
                "role": "assistant",
                "content": "".join(content_parts) or None,
                "tool_calls": assistant_tool_calls,
            })

            for call in assistant_tool_calls:
                if call["type"] != "function":
                    continue
                tool_calls_total += 1
                if tool_calls_total > self.settings.max_tool_calls:
                    raise RuntimeError("tool call limit exceeded")
                function = call["function"]
                target = next((tool for tool in tools if tool.model_name == function["name"]), None)
                if target is None:
                    raise RuntimeError(f"unknown tool: {function['name']}")
                try:
                    args = json.loads(function["arguments"] or "{}")
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"invalid arguments for tool {function['name']}") from exc
                if not isinstance(args, dict):
                    raise RuntimeError(f"tool arguments for {function['name']} must be an object")
                result = await self.registry.call(target.server, target.name, args)
                new_evidence: list[CitationEvidence] = []
                for item in _extract_rag_evidence(result):
                    if item not in evidence:
                        evidence.append(item)
                        new_evidence.append(item)
                result_text = _result_text(result)
                if new_evidence:
                    start = len(evidence) - len(new_evidence) + 1
                    result_text = f"RAG evidence sources S{start}..S{len(evidence)}:\n{result_text}"
                    for index, item in enumerate(new_evidence, start=start):
                        result_text += f"\n[S{index}] source={item.source_name} chunk={item.chunk_id}: {item.text}"
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": ContextBudget(
                        self.settings.max_tool_result_chars,
                        self.settings.context_reserve_chars,
                    ).bound(result_text),
                })

        raise RuntimeError("agent iteration limit exceeded")

    async def _run(
        self,
        message: str,
        model: str | None = None,
        *,
        system_prompt: str | None = None,
        allowed_server_names: set[str] | None = None,
        collect_citations: bool = False,
        history: list[dict[str, str]] | None = None,
    ) -> AgentResult:
        tools = await self.registry.list_tools()
        if allowed_server_names is not None:
            tools = [tool for tool in tools if tool.server_name in allowed_server_names]
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
        messages: list[Any] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(ContextBudget(self.settings.max_tool_result_chars, self.settings.context_reserve_chars).bound_messages(history))
        messages.append({"role": "user", "content": message})
        tool_calls_total = 0
        evidence: list[CitationEvidence] = []

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
                return AgentResult(
                    content=choice.message.content or "",
                    iterations=iteration,
                    tool_calls=tool_calls_total,
                    citations=tuple(evidence),
                )

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

                target = next((tool for tool in tools if tool.model_name == function.name), None)
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
                new_evidence: list[CitationEvidence] = []
                if collect_citations and target.server_name == "rag":
                    for item in _extract_rag_evidence(result):
                        if item not in evidence:
                            evidence.append(item)
                            new_evidence.append(item)
                result_text = _result_text(result)
                if new_evidence:
                    start = len(evidence) - len(new_evidence) + 1
                    result_text = f"RAG evidence sources S{start}..S{len(evidence)}:\n{result_text}"
                    for index, item in enumerate(new_evidence, start=start):
                        result_text += f"\n[S{index}] source={item.source_name} chunk={item.chunk_id}: {item.text}"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": ContextBudget(
                            self.settings.max_tool_result_chars,
                            self.settings.context_reserve_chars,
                        ).bound(result_text),
                    }
                )

        raise RuntimeError("agent iteration limit exceeded")
