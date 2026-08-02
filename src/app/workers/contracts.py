from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID


class InvalidTaskEnvelope(ValueError):
    """A queue message failed the application-level task contract."""


@dataclass(frozen=True)
class TaskEnvelope:
    """JSON-safe identity and retry metadata sent through the broker."""

    job_id: UUID
    tenant_id: str
    idempotency_key: str
    task_type: str
    task_payload: str | None
    max_attempts: int

    def __post_init__(self) -> None:
        if not self.tenant_id.strip() or not self.idempotency_key.strip():
            raise InvalidTaskEnvelope("tenant_id and idempotency_key are required")
        if not self.task_type.strip():
            raise InvalidTaskEnvelope("task_type is required")
        if not 1 <= self.max_attempts <= 10:
            raise InvalidTaskEnvelope("max_attempts must be between 1 and 10")

    @classmethod
    def from_job(cls, job: Any) -> TaskEnvelope:
        return cls(
            job_id=job.job_id,
            tenant_id=job.tenant_id,
            idempotency_key=job.idempotency_key,
            task_type=job.task_type,
            task_payload=job.task_payload,
            max_attempts=job.max_attempts,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> TaskEnvelope:
        try:
            return cls(
                job_id=UUID(str(value["job_id"])),
                tenant_id=str(value["tenant_id"]),
                idempotency_key=str(value["idempotency_key"]),
                task_type=str(value["task_type"]),
                task_payload=(
                    None
                    if value.get("task_payload") is None
                    else str(value["task_payload"])
                ),
                max_attempts=int(value["max_attempts"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidTaskEnvelope("invalid task envelope") from exc

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "job_id": str(self.job_id),
            "tenant_id": self.tenant_id,
            "idempotency_key": self.idempotency_key,
            "task_type": self.task_type,
            "task_payload": self.task_payload,
            "max_attempts": self.max_attempts,
        }
