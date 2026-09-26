from typing import Literal

from pydantic import BaseModel, Field


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=10_000)


class ConversationContext(BaseModel):
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128)
    messages: list[ConversationMessage] = Field(default_factory=list, max_length=20)


class ChatRequest(ConversationContext):
    message: str = Field(min_length=1, max_length=20_000)
    model: str | None = None


class ChatResponse(BaseModel):
    content: str
    conversation_id: str | None
    iterations: int
    tool_calls: int


class AnswerRequest(ConversationContext):
    question: str = Field(min_length=1, max_length=20_000)
    model: str | None = None


class Citation(BaseModel):
    id: str
    chunk_id: str
    source_name: str
    text: str


class AnswerResponse(BaseModel):
    answer: str
    citations: list[Citation]
    conversation_id: str | None
    iterations: int
    tool_calls: int


class ToolInfo(BaseModel):
    name: str
    qualified_name: str
    model_name: str
    description: str | None = None
