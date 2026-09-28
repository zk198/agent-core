from typing import Any

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant|tool)$")
    content: str = Field(min_length=1, max_length=100_000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] | None = Field(default=None, min_length=1, max_length=100)
    message: str | None = Field(default=None, min_length=1, max_length=20_000)
    model: str | None = None


class ChatResponse(BaseModel):
    content: str
    iterations: int
    tool_calls: int
    trace: dict[str, Any] | None = None


class AnswerRequest(BaseModel):
    question: str | None = Field(default=None, min_length=1, max_length=20_000)
    messages: list[ChatMessage] | None = Field(default=None, min_length=1, max_length=100)
    model: str | None = None


class Citation(BaseModel):
    id: str
    chunk_id: str
    source_name: str
    text: str


class AnswerResponse(BaseModel):
    answer: str
    citations: list[Citation]
    iterations: int
    tool_calls: int
    trace: dict[str, Any] | None = None


class ToolInfo(BaseModel):
    name: str
    qualified_name: str
    model_name: str
    description: str | None = None
