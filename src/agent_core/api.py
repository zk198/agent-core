import json
import logging
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from .agent import Agent
from .config import Settings
from .mcp_client import MCPRegistry
from .models import AnswerRequest, AnswerResponse, ChatRequest, ChatResponse, Citation, ToolInfo
from .observability import current_trace, normalize_request_id, reset_request_id, set_request_id, start_trace

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent_core")

settings = Settings()
registry = MCPRegistry(settings.mcp_server_configs())
agent = Agent(settings, registry)

app = FastAPI(title="Agent Core", version="0.3.0")


@app.middleware("http")
async def request_logging(request: Request, call_next):
    request_value = normalize_request_id(request.headers.get("X-Request-ID"))
    token = set_request_id(request_value)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request_failed request_id=%s method=%s path=%s",
            request_value, request.method, request.url.path,
        )
        reset_request_id(token)
        raise
    logger.info(
        "request request_id=%s method=%s path=%s status=%s agent_ms=%.1f",
        request_value,
        request.method,
        request.url.path,
        response.status_code,
        (time.perf_counter() - started) * 1000,
    )
    response.headers["X-Request-ID"] = request_value
    reset_request_id(token)
    return response


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/ready")
async def ready() -> dict[str, str]:
    try:
        await registry.list_tools()
    except Exception as exc:
        logger.warning("readiness_failed error=%s", exc)
        raise HTTPException(status_code=503, detail="MCP dependencies unavailable") from exc
    return {"status": "ready"}


@app.get("/api/v1/tools")
async def tools() -> list[ToolInfo]:
    discovered = await registry.list_tools()
    return [
        ToolInfo(
            name=tool.name,
            qualified_name=tool.qualified_name,
            model_name=tool.model_name,
            description=tool.description,
        )
        for tool in discovered
    ]


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    trace, trace_token = start_trace()
    try:
        if request.messages:
            input_messages = [item.model_dump() for item in request.messages]
        elif request.message:
            input_messages = [{"role": "user", "content": request.message}]
        else:
            raise HTTPException(status_code=422, detail="message or messages is required")
        content, iterations, tool_calls = await agent.run_messages(input_messages, request.model)
        trace.complete(status="completed")
        return ChatResponse(content=content, iterations=iterations, tool_calls=tool_calls, trace=trace.to_dict())
    except ValueError as exc:
        trace.complete(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        trace.complete(status="failed")
        raise
    except Exception as exc:
        trace.complete(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
        logger.exception("agent_run_failed")
        raise HTTPException(status_code=502, detail="agent dependency failed") from exc
    finally:
        reset_trace(trace_token)


@app.post("/api/v1/answer/stream")
async def answer_stream(request: AnswerRequest) -> StreamingResponse:
    input_messages = [item.model_dump() for item in request.messages] if request.messages else None
    if not input_messages and not request.question:
        raise HTTPException(status_code=422, detail="question or messages is required")

    async def events():
        trace, trace_token = start_trace()
        try:
            async for item in agent.stream_grounded_answer(
                request.question, request.model, conversation_messages=input_messages
            ):
                if item["type"] == "delta":
                    yield f"event: delta\ndata: {json.dumps({'content': item['content']}, ensure_ascii=False)}\n\n"
                else:
                    trace.complete(status="completed")
                    citations = [
                        {"id": f"S{index}", "chunk_id": citation.chunk_id, "source_name": citation.source_name, "text": citation.text}
                        for index, citation in enumerate(item["citations"], start=1)
                    ]
                    payload = json.dumps({
                        "citations": citations,
                        "iterations": item["iterations"],
                        "tool_calls": item["tool_calls"],
                        "trace_id": trace.trace_id,
                        "trace": trace.to_dict(),
                    }, ensure_ascii=False)
                    yield f"event: done\ndata: {payload}\n\n"
        except Exception as exc:
            trace.complete(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
            logger.exception("grounded_answer_stream_failed")
            yield f"event: error\ndata: {json.dumps({'detail': 'grounded answer dependency failed', 'trace_id': trace.trace_id})}\n\n"
        finally:
            reset_trace(trace_token)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/v1/answer", response_model=AnswerResponse)
async def answer(request: AnswerRequest) -> AnswerResponse:
    trace, trace_token = start_trace()
    try:
        input_messages = [item.model_dump() for item in request.messages] if request.messages else None
        if not input_messages and not request.question:
            raise HTTPException(status_code=422, detail="question or messages is required")
        result = await agent.run_grounded_answer(request.question, request.model, messages=input_messages)
        trace.complete(status="completed")
        citations = [
            Citation(id=f"S{index}", chunk_id=item.chunk_id, source_name=item.source_name, text=item.text)
            for index, item in enumerate(result.citations, start=1)
        ]
        return AnswerResponse(
            answer=result.content,
            citations=citations,
            iterations=result.iterations,
            tool_calls=result.tool_calls,
            trace=trace.to_dict(),
        )
    except ValueError as exc:
        trace.complete(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        trace.complete(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
        logger.exception("grounded_answer_failed")
        raise HTTPException(status_code=502, detail="grounded answer dependency failed") from exc
    finally:
        reset_trace(trace_token)
