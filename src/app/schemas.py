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


class DocumentUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1, max_length=14_000_000)
    content_type: str | None = Field(default=None, max_length=128)
    parser_version: str = Field(default="parser-v1", min_length=1, max_length=64)
    chunker_version: str = Field(default="chunker-v1", min_length=1, max_length=64)
    embedding_model: str = Field(default="pending", min_length=1, max_length=255)
    embedding_dimension: int = Field(default=1, ge=1, le=100_000)
    index_version: str = Field(default="pending", min_length=1, max_length=128)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class DocumentUploadResponse(BaseModel):
    document_id: str
    job_id: str | None
    status: str
    created: bool


class DocumentStatusResponse(BaseModel):
    document_id: str
    tenant_id: str
    original_name: str
    content_hash: str
    document_version: int
    status: str
    index_version: str


class IngestionJobResponse(BaseModel):
    job_id: str
    document_id: str | None = None
    tenant_id: str
    status: str
    error: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
