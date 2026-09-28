from __future__ import annotations

import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_request_id: ContextVar[str | None] = ContextVar("agent_request_id", default=None)
_trace: ContextVar[ExecutionTrace | None] = ContextVar("agent_execution_trace", default=None)


def set_request_id(value: str):
    return _request_id.set(value)


def reset_request_id(token) -> None:
    _request_id.reset(token)


def request_id() -> str | None:
    return _request_id.get()


def normalize_request_id(value: str | None) -> str:
    return (value or uuid.uuid4().hex).strip()[:128]


class ExecutionTrace:
    """Canonical full-fidelity execution trace."""

    schema_version = "1.0"

    def __init__(self, *, trace_id: str | None = None, request_id_value: str | None = None) -> None:
        self.trace_id = trace_id or uuid.uuid4().hex
        self.request_id = request_id_value or request_id()
        self.started_at = datetime.now(UTC).isoformat()
        self._started = time.perf_counter()
        self.completed_at: str | None = None
        self.status = "running"
        self.error: dict[str, Any] | None = None
        self.logs: list[dict[str, Any]] = []
        self.metrics: dict[str, Any] = {}
        self.events: list[dict[str, Any]] = []
        self._sequence = 0

    def event(
        self,
        *,
        kind: str,
        stage: str,
        name: str,
        payload: dict[str, Any] | None = None,
        parent_id: str | None = None,
        status: str = "running",
    ) -> str:
        self._sequence += 1
        event_id = uuid.uuid4().hex
        self.events.append(
            {
                "event_id": event_id,
                "parent_id": parent_id,
                "sequence": self._sequence,
                "kind": kind,
                "stage": stage,
                "name": name,
                "status": status,
                "started_at": datetime.now(UTC).isoformat(),
                "duration_ms": None,
                "payload": payload or {},
            }
        )
        return event_id

    def finish_event(
        self,
        event_id: str,
        *,
        status: str = "completed",
        payload: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> None:
        for item in self.events:
            if item["event_id"] == event_id:
                item["status"] = status
                item["duration_ms"] = duration_ms
                if payload:
                    item["payload"].update(payload)
                item["completed_at"] = datetime.now(UTC).isoformat()
                return

    def log(self, *, level: str, message: str, **fields: Any) -> None:
        self.logs.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": level,
                "message": message,
                **fields,
            }
        )

    def metric(self, name: str, value: Any) -> None:
        self.metrics[name] = value

    def complete(
        self,
        *,
        status: str = "completed",
        error: dict[str, Any] | None = None,
    ) -> None:
        self.status = status
        self.error = error
        self.completed_at = datetime.now(UTC).isoformat()
        self.metrics["duration_ms"] = round((time.perf_counter() - self._started) * 1000, 1)
        self.metrics["trace_events"] = len(self.events)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.metrics.get("duration_ms"),
            "status": self.status,
            "error": self.error,
            "logs": self.logs,
            "metrics": self.metrics,
            "trace": self.events,
        }


def start_trace() -> tuple[ExecutionTrace, Any]:
    trace = ExecutionTrace()
    return trace, _trace.set(trace)


def current_trace() -> ExecutionTrace | None:
    return _trace.get()


def reset_trace(token: Any) -> None:
    _trace.reset(token)
