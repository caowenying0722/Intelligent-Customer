"""Application service joining upload validation, storage and background jobs."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.app.application.ingestion import IngestionJob, IngestionJobManager
from src.app.application.upload_storage import SecureUploadStorage
from src.app.application.uploads import ValidatedUpload, validate_upload


class DocumentIngestionService:
    def __init__(
        self, storage: SecureUploadStorage, jobs: IngestionJobManager
    ) -> None:
        self.storage = storage
        self.jobs = jobs
        self._lock = threading.Lock()

    def submit(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        filename: str,
        content: bytes,
        content_type: str | None,
        operation: Callable[[Path, ValidatedUpload], Any],
    ) -> IngestionJob:
        """Validate/save synchronously, then enqueue expensive work exactly once."""
        with self._lock:
            existing = self.jobs.get_by_idempotency(
                tenant_id=tenant_id, idempotency_key=idempotency_key
            )
            if existing is not None:
                return existing
            upload = validate_upload(filename, content, content_type)
            path = self.storage.persist(upload)
            try:
                return self.jobs.submit(
                    tenant_id=tenant_id,
                    idempotency_key=idempotency_key,
                    operation=lambda: operation(path, upload),
                )
            except Exception:
                self.storage.remove(upload.storage_name)
                raise
