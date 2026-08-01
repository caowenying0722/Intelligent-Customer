"""Stable provider-neutral model request/response contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    request_id: str | None = None
    prompt_version: str = "v1"


class ModelUsage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost: str = "0"
    latency_ms: float = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    cache_hit: bool = False


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    output: str
    finish_reason: str = "stop"
    usage: ModelUsage = ModelUsage()
    retry_count: int = Field(default=0, ge=0)
    fallback_chain: list[str] = Field(default_factory=list)
    trace_metadata: dict[str, str] = Field(default_factory=dict)
