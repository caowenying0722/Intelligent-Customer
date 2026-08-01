"""Stable HTTP schemas for the first chat endpoint."""

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    expected_version: int | None = Field(default=None, ge=0)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class ChatResponse(BaseModel):
    request_id: str
    answer: str
    conversation_id: str
    run_id: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str


class MessageResponse(BaseModel):
    role: str
    content: str
    created_at: str


class ConversationResponse(BaseModel):
    conversation_id: str
    version: int
    user_id: str
    status: str
    messages: list[MessageResponse]


class RunUpdateRequest(BaseModel):
    status: str
    error: str | None = None


class AgentRunResponse(BaseModel):
    run_id: str
    conversation_id: str
    status: str
    error: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None


class AgentRunListResponse(BaseModel):
    items: list[AgentRunResponse]
    limit: int
    offset: int
