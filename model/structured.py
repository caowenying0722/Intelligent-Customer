"""Provider-neutral structured response validation."""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError


ModelT = TypeVar("ModelT", bound=BaseModel)


def validate_structured(value: Any, schema: type[ModelT]) -> ModelT:
    if not isinstance(schema, type) or not issubclass(schema, BaseModel):
        raise TypeError("schema must be a Pydantic BaseModel class")
    try:
        if isinstance(value, BaseModel):
            return schema.model_validate(value.model_dump())
        return schema.model_validate(value)
    except ValidationError as exc:
        raise ValueError("model response did not match the requested schema") from exc
