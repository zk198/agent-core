import json
import logging
import time
from dataclasses import dataclass
from typing import Any, cast

from openai import AsyncOpenAI

from .config import Settings
from .context import ContextBudget
from .mcp_client import (
    MCPRegistry,
    MCPToolArgumentError,
    MCPToolArgumentsJSONError,
    MCPToolResolutionError,
    validate_tool_arguments,
)
from .laya_client import LayaClient
from .observability import current_trace, request_id

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
    evidence: list[CitationEvidence] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            chunk_id = node.get("chunk_id")
            text = node.get("text")
            source_name = node.get("source_name")
            if isinstance(chunk_id, str) and isinstance(text, str) and isinstance(source_name, str):
                item = CitationEvidence(chunk_id=chunk_id, source_name=source_name, text=text)
                if item not in evidence:
                    evidence.append(item)
                return
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, str):
            try:
                decoded = json.loads(node)
            except json.JSONDecodeError:
                return
            if decoded != node:
                visit(decoded)

    visit(structured)
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
        self.laya = LayaClient(settings.laya_url, settings.laya_timeout_seconds, settings.laya_api_key)

    async def _laya_decision(self, state: object, *, parent_id: str | None = None) -> dict | None:
        if not self.settings.laya_enabled or not self.settings.laya_questions_json.strip():
            return None
        trace = current_trace()
        event_id = trace.event(
            kind="system1",
            stage="laya",
            name="laya.systemone",
            payload={"enabled": True, "model": "auto"},
            parent_id=parent_id,
        ) if trace else None
        started = time.perf_counter()
        try:
            questions = json.loads(self.settings.laya_questions_json)
            if not isinstance(questions, dict) or not questions:
                raise ValueError("AGENT_LAYA_QUESTIONS_JSON must be a non-empty JSON object")
            result = await self.laya.decide(state, questions)
            latency = round((time.perf_counter() - started) * 1000, 1)
            if trace and event_id:
                trace.finish_event(
                    event_id,
                    duration_ms=latency,
                    payload={
                        "routing": _structured_value(result.get("routing")),
                        "answers": _structured_value(result.get("answers")),
                        "latency_ms": latency,
                    },
                )
            if self.settings.laya_enforce:
                allowed = result.get("answers", {}).get("allowed", {}).get("noul")
                if allowed is not True:
                    raise PermissionError("Laya guardrail denied or returned no allowed decision")
            return result
        except Exception as exc:
            latency = round((time.perf_counter() - started) * 1000, 1)
            if trace and event_id:
                trace.finish_event(
                    event_id,
                    status="failed",
                    duration_ms=latency,
                    payload={"error": {"type": type(exc).__name__, "message": str(exc)}, "latency_ms": latency},
                )
            if self.settings.laya_enforce:
                raise
            logger.warning("laya_decision_failed request_id=%s error=%s", request_id(), type(exc).__name__)
            return None

    async def run(
        self,
        message: str,
        model: str | None = None,
        *,
        system_prompt: str | None = None,
        allowed_server_names: set[str] | None = None,
    ) -> tuple[str, int, int]:
        return await self.run_messages(
            [{"role": "user", "content": message}],
            model,
            system_prompt=system_prompt,
            allowed_server_names=allowed_server_names,
        )

    async def run_messages(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        *,
        system_prompt: str | None = None,
        allowed_server_names: set[str] | None = None,
    ) -> tuple[str, int, int]:
        result = await self._run(
            messages,
            model,
            system_prompt=system_prompt,
            allowed_server_names=allowed_server_names,
        )
        return result.content, result.iterations, result.tool_calls

    async def run_grounded_answer(
        self,
        question: str | None = None,
        model: str | None = None,
        *,
        messages: list[dict[str, Any]] | None = None,
    ) -> AgentResult:
        input_messages = messages or ([{"role": "user", "content": question}] if question else [])
        if not input_messages:
            raise ValueError("question or messages is required")
        return await self._run(
            input_messages,
            model,
            system_prompt=(
                "You are a grounded knowledge assistant. Answer using only evidence returned "
                "by the RAG tools. Cite factual claims with the supplied citation IDs such as [S1]. "
                "Do not invent citations or facts. If the evidence is insufficient, say so explicitly."
            ),
            allowed_server_names={"rag"},
            collect_citations=True,
        )

    async def stream_grounded_answer(
        self,
        question: str | None = None,
        model: str | None = None,
        *,
        conversation_messages: list[dict[str, Any]] | None = None,
    ):
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
        input_messages: list[Any] = conversation_messages or (
            [{"role": "user", "content": question}] if question else []
        )
        if not input_messages:
            raise ValueError("question or messages is required")
        messages: list[Any] = [{"role": "system", "content": system_prompt}, *input_messages]
        evidence: list[CitationEvidence] = []
        tool_calls_total = 0
        trace = current_trace()
        agent_event = None
        if trace:
            agent_event = trace.event(
                kind="agent", stage="agent", name="agent.stream_grounded_answer",
                payload={
                    "input_messages": input_messages,
                    "model": model or self.settings.model_name,
                    "system_prompt": system_prompt,
                },
            )
        await self._laya_decision(input_messages, parent_id=agent_event)

        for iteration in range(1, self.settings.max_iterations + 1):
            llm_started = time.perf_counter()
            llm_event = None
            if trace:
                llm_event = trace.event(
                    kind="llm", stage="llm", name=f"iteration.{iteration}",
                    payload={"model": model or self.settings.model_name, "messages": messages, "tools": openai_tools},
                    parent_id=agent_event,
                )
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

            llm_ms = (time.perf_counter() - llm_started) * 1000
            logger.info(
                "llm_stage request_id=%s llm_ms=%.1f iteration=%s streaming=true",
                request_id(), llm_ms, iteration,
            )
            if trace and llm_event:
                trace.finish_event(
                    llm_event, duration_ms=round(llm_ms, 1),
                    payload={"response": {"content": "".join(content_parts), "tool_calls": list(tool_calls.values())}},
                )

            if not tool_calls:
                yield {
                    "type": "done",
                    "citations": evidence,
                    "iterations": iteration,
                    "tool_calls": tool_calls_total,
                }
                if trace:
                    if agent_event:
                        trace.finish_event(agent_event, status="completed")
                    trace.complete(status="completed")
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
                    raise MCPToolResolutionError(f"unknown tool: {function['name']}")
                try:
                    args = json.loads(function["arguments"] or "{}")
                except json.JSONDecodeError as exc:
                    raise MCPToolArgumentsJSONError(f"invalid JSON arguments for tool {function['name']}") from exc
                if not isinstance(args, dict):
                    error = RuntimeError(f"tool arguments for {function['name']} must be an object")
                    if trace:
                        failed_event = trace.event(
                            kind="tool", stage="retrieval" if target.server_name == "rag" else "tool",
                            name=target.qualified_name,
                            payload={"server": target.server_name, "tool": target.name}, parent_id=llm_event,
                        )
                        trace.finish_event(
                            failed_event,
                            status="failed",
                            payload={"error": {"type": type(error).__name__, "message": str(error)}},
                        )
                        trace.complete(status="failed", error={"type": type(error).__name__, "message": str(error)})
                    raise error
                try:
                    validate_tool_arguments(target, args)
                except MCPToolArgumentError as exc:
                    if trace:
                        failed_event = trace.event(
                            kind="tool", stage="retrieval" if target.server_name == "rag" else "tool",
                            name=target.qualified_name,
                            payload={
                                "server": target.server_name,
                                "tool": target.name,
                                "arguments": args,
                            },
                            parent_id=llm_event,
                        )
                        trace.finish_event(
                            failed_event,
                            status="failed",
                            payload={"error": {"type": type(exc).__name__, "message": str(exc)}},
                        )
                        trace.complete(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
                    raise
                tool_started = time.perf_counter()
                tool_event = None
                if trace:
                    tool_event = trace.event(
                        kind="tool",
                        stage="retrieval" if target.server_name == "rag" else "tool",
                        name=target.qualified_name,
                        payload={"server": target.server_name, "tool": target.name, "arguments": args},
                        parent_id=llm_event,
                    )
                try:
                    result = await self.registry.call(target.server, target.name, args)
                except Exception as exc:
                    if trace and tool_event:
                        trace.finish_event(
                            tool_event,
                            status="failed",
                            duration_ms=round((time.perf_counter() - tool_started) * 1000, 1),
                            payload={"error": {"type": type(exc).__name__, "message": str(exc)}},
                        )
                        trace.complete(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
                    raise
                tool_ms = (time.perf_counter() - tool_started) * 1000
                if trace and tool_event:
                    trace.finish_event(
                        tool_event, duration_ms=round(tool_ms, 1),
                        payload={"result": _structured_value(result)},
                    )
                stage = "retrieval" if target.server_name == "rag" else "tool"
                logger.info(
                    "tool_stage request_id=%s stage=%s tool=%s tool_ms=%.1f",
                    request_id(), stage, target.qualified_name, tool_ms,
                )
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

        if trace:
            if agent_event:
                trace.finish_event(
                    agent_event,
                    status="failed",
                    payload={"error": {"type": "RuntimeError", "message": "agent iteration limit exceeded"}},
                )
            trace.complete(status="failed", error={"type": "RuntimeError", "message": "agent iteration limit exceeded"})
        raise RuntimeError("agent iteration limit exceeded")

    async def _run(
        self,
        input_messages: list[dict[str, Any]],
        model: str | None = None,
        *,
        system_prompt: str | None = None,
        allowed_server_names: set[str] | None = None,
        collect_citations: bool = False,
    ) -> AgentResult:
        trace = current_trace()
        agent_event = None
        if trace:
            agent_event = trace.event(
                kind="agent", stage="agent", name="agent.run",
                payload={
                    "input_messages": input_messages,
                    "model": model or self.settings.model_name,
                    "system_prompt": system_prompt,
                    "allowed_server_names": sorted(allowed_server_names) if allowed_server_names else None,
                },
                status="running",
            )
        await self._laya_decision(input_messages, parent_id=agent_event)
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
        messages: list[Any] = [dict(message) for message in input_messages]
        if system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})
        tool_calls_total = 0
        evidence: list[CitationEvidence] = []

        for iteration in range(1, self.settings.max_iterations + 1):
            logger.info(
                "agent iteration=%d tool_count=%d tool_calls=%d",
                iteration,
                len(tools),
                tool_calls_total,
            )
            llm_started = time.perf_counter()
            llm_event = None
            if trace:
                llm_event = trace.event(
                    kind="llm", stage="llm", name=f"iteration.{iteration}",
                    payload={"model": model or self.settings.model_name, "messages": messages, "tools": openai_tools},
                    parent_id=agent_event,
                )
            response = await self.client.chat.completions.create(
                model=model or self.settings.model_name,
                messages=messages,
                tools=cast(Any, openai_tools or None),
            )
            llm_ms = (time.perf_counter() - llm_started) * 1000
            logger.info(
                "llm_stage request_id=%s stage=llm llm_ms=%.1f iteration=%s streaming=false",
                request_id(), llm_ms, iteration,
            )
            if trace and llm_event:
                trace.finish_event(
                    llm_event, duration_ms=round(llm_ms, 1),
                    payload={"response": response.model_dump(exclude_none=True)},
                )
            if not response.choices:
                raise RuntimeError("model returned no choices")

            choice = response.choices[0]
            if not choice.message.tool_calls:
                result = AgentResult(
                    content=choice.message.content or "",
                    iterations=iteration,
                    tool_calls=tool_calls_total,
                    citations=tuple(evidence),
                )
                if trace:
                    if agent_event:
                        trace.finish_event(agent_event, status="completed")
                    trace.complete(status="completed")
                return result

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
                    raise MCPToolResolutionError(f"unknown tool: {function.name}")

                try:
                    args = json.loads(function.arguments or "{}")
                except json.JSONDecodeError as exc:
                    raise MCPToolArgumentsJSONError(f"invalid JSON arguments for tool {function.name}") from exc
                if not isinstance(args, dict):
                    error = RuntimeError(f"tool arguments for {function.name} must be an object")
                    if trace:
                        failed_event = trace.event(
                            kind="tool", stage="retrieval" if target.server_name == "rag" else "tool",
                            name=target.qualified_name,
                            payload={"server": target.server_name, "tool": target.name}, parent_id=llm_event,
                        )
                        trace.finish_event(
                            failed_event,
                            status="failed",
                            payload={"error": {"type": type(error).__name__, "message": str(error)}},
                        )
                        trace.complete(status="failed", error={"type": type(error).__name__, "message": str(error)})
                    raise error
                try:
                    validate_tool_arguments(target, args)
                except MCPToolArgumentError as exc:
                    if trace:
                        failed_event = trace.event(
                            kind="tool", stage="retrieval" if target.server_name == "rag" else "tool",
                            name=target.qualified_name,
                            payload={
                            "server": target.server_name,
                            "tool": target.name,
                            "arguments": args,
                        },
                        parent_id=llm_event,
                        )
                        trace.finish_event(
                            failed_event,
                            status="failed",
                            payload={"error": {"type": type(exc).__name__, "message": str(exc)}},
                        )
                        trace.complete(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
                    raise

                logger.info(
                    "agent tool_call=%s server=%s raw_tool=%s",
                    target.model_name,
                    target.server_name,
                    target.name,
                )
                tool_started = time.perf_counter()
                tool_event = None
                if trace:
                    tool_event = trace.event(
                        kind="tool",
                        stage="retrieval" if target.server_name == "rag" else "tool",
                        name=target.qualified_name,
                        payload={"server": target.server_name, "tool": target.name, "arguments": args},
                        parent_id=llm_event,
                    )
                try:
                    result = await self.registry.call(target.server, target.name, args)
                except Exception as exc:
                    if trace and tool_event:
                        trace.finish_event(
                            tool_event,
                            status="failed",
                            duration_ms=round((time.perf_counter() - tool_started) * 1000, 1),
                            payload={"error": {"type": type(exc).__name__, "message": str(exc)}},
                        )
                        trace.complete(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
                    raise
                tool_ms = (time.perf_counter() - tool_started) * 1000
                if trace and tool_event:
                    trace.finish_event(
                        tool_event, duration_ms=round(tool_ms, 1),
                        payload={"result": _structured_value(result)},
                    )
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

        if trace and agent_event:
            trace.finish_event(
                agent_event,
                status="failed",
                payload={"error": {"type": "RuntimeError", "message": "agent iteration limit exceeded"}},
            )
            trace.complete(status="failed", error={"type": "RuntimeError", "message": "agent iteration limit exceeded"})
        raise RuntimeError("agent iteration limit exceeded")
