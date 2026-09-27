from __future__ import annotations

import uuid
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("agent_request_id", default=None)

def set_request_id(value: str): return _request_id.set(value)
def reset_request_id(token) -> None: _request_id.reset(token)
def request_id() -> str | None: return _request_id.get()
def normalize_request_id(value: str | None) -> str: return (value or uuid.uuid4().hex).strip()[:128]
