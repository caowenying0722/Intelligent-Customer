"""Stable HTTP schemas for the first chat endpoint."""

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    request_id: str
    answer: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str
