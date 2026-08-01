"""Stable HTTP schemas for the first chat endpoint."""

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    request_id: str
    answer: str
    conversation_id: str


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
    messages: list[MessageResponse]
