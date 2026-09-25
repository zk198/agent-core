from pydantic import BaseModel, Field

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    model: str | None = None

class ChatResponse(BaseModel):
    content: str
    iterations: int
    tool_calls: int

class ToolInfo(BaseModel):
    name: str
    description: str | None = None
