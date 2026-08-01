"""SQLAlchemy persistence adapter for document metadata and ingestion jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.app.application.document_metadata import (
    DocumentMetadataRegistry,
    DocumentRecord,
    DocumentStatus,
)
from src.app.application.ingestion import IngestionJob, IngestionJobStatus
from src.app.application.uploads import ValidatedUpload
from src.app.infrastructure.postgres import DocumentRow, IngestionJobRow
from src.app.infrastructure.postgres import SqlAlchemyConversationRepository


class SqlAlchemyIngestionRepository:
    def __init__(self, database_url: str, *, initialize_schema: bool = False) -> None:
        self._repository = SqlAlchemyConversationRepository(
            database_url, initialize_schema=initialize_schema
        )
        self.engine = self._repository.engine

    def close(self) -> None:
        self._repository.close()

    def create_document(self, record: DocumentRecord) -> DocumentRecord:
        with Session(self.engine) as session:
            session.add(
                DocumentRow(
                    id=str(record.document_id),
                    tenant_id=record.tenant_id,
                    original_name=record.original_name,
                    storage_name=record.storage_name,
                    content_hash=record.content_hash,
                    document_version=record.document_version,
                    parser_version=record.parser_version,
                    chunker_version=record.chunker_version,
                    embedding_model=record.embedding_model,
                    embedding_dimension=record.embedding_dimension,
                    index_version=record.index_version,
                    status=record.status.value,
                    created_at=record.created_at,
                )
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = session.scalar(
                    select(DocumentRow).where(
                        DocumentRow.tenant_id == record.tenant_id,
                        DocumentRow.content_hash == record.content_hash,
                    )
                )
                if existing is None:
                    raise
                return self._document(existing)
        return record

    def get_document(self, *, tenant_id: str, document_id: UUID) -> DocumentRecord | None:
        with Session(self.engine) as session:
            row = session.scalar(
                select(DocumentRow).where(
                    DocumentRow.tenant_id == tenant_id,
                    DocumentRow.id == str(document_id),
                )
            )
            return self._document(row) if row else None

    def get(self, *, tenant_id: str, document_id: UUID) -> DocumentRecord | None:
        return self.get_document(tenant_id=tenant_id, document_id=document_id)

    def get_by_hash(self, *, tenant_id: str, content_hash: str) -> DocumentRecord | None:
        with Session(self.engine) as session:
            row = session.scalar(
                select(DocumentRow).where(
                    DocumentRow.tenant_id == tenant_id,
                    DocumentRow.content_hash == content_hash,
                )
            )
            return self._document(row) if row else None

    def register(
        self, *, tenant_id: str, upload: ValidatedUpload, parser_version: str,
        chunker_version: str, embedding_model: str, embedding_dimension: int,
        index_version: str,
    ) -> tuple[DocumentRecord, bool]:
        existing = self.get_by_hash(tenant_id=tenant_id, content_hash=upload.sha256)
        if existing is not None:
            return existing, False
        record, _ = DocumentMetadataRegistry().register(
            tenant_id=tenant_id, upload=upload, parser_version=parser_version,
            chunker_version=chunker_version, embedding_model=embedding_model,
            embedding_dimension=embedding_dimension, index_version=index_version,
        )
        return self.create_document(record), True

    def update_document_status(
        self, *, tenant_id: str, document_id: UUID, status: DocumentStatus
    ) -> DocumentRecord:
        with Session(self.engine) as session:
            row = session.scalar(
                select(DocumentRow).where(
                    DocumentRow.tenant_id == tenant_id,
                    DocumentRow.id == str(document_id),
                )
            )
            if row is None:
                raise KeyError("document not found")
            row.status = status.value
            session.commit()
            return self._document(row)

    def update_status(
        self, *, tenant_id: str, document_id: UUID, status: DocumentStatus
    ) -> DocumentRecord:
        return self.update_document_status(
            tenant_id=tenant_id, document_id=document_id, status=status
        )

    def create_job(
        self, *, job: IngestionJob, document_id: UUID
    ) -> IngestionJob:
        with Session(self.engine) as session:
            existing = session.scalar(
                select(IngestionJobRow).where(
                    IngestionJobRow.tenant_id == job.tenant_id,
                    IngestionJobRow.idempotency_key == job.idempotency_key,
                )
            )
            if existing is not None:
                return self._job(existing)
            session.add(
                IngestionJobRow(
                    id=str(job.job_id),
                    tenant_id=job.tenant_id,
                    document_id=str(document_id),
                    idempotency_key=job.idempotency_key,
                    status=job.status.value,
                    created_at=job.created_at,
                )
            )
            session.commit()
        return job

    def get_job(self, *, tenant_id: str, job_id: UUID) -> IngestionJob | None:
        with Session(self.engine) as session:
            row = session.scalar(
                select(IngestionJobRow).where(
                    IngestionJobRow.tenant_id == tenant_id,
                    IngestionJobRow.id == str(job_id),
                )
            )
            return self._job(row) if row else None

    def update_job_status(
        self, *, tenant_id: str, job_id: UUID, status: IngestionJobStatus, error: str | None = None
    ) -> IngestionJob:
        with Session(self.engine) as session:
            row = session.scalar(
                select(IngestionJobRow).where(
                    IngestionJobRow.tenant_id == tenant_id,
                    IngestionJobRow.id == str(job_id),
                )
            )
            if row is None:
                raise KeyError("ingestion job not found")
            row.status = status.value
            row.error = error[:500] if error else None
            if status == IngestionJobStatus.RUNNING:
                row.started_at = datetime.now(timezone.utc)
            if status in {
                IngestionJobStatus.COMPLETED,
                IngestionJobStatus.FAILED,
                IngestionJobStatus.CANCELLED,
            }:
                row.completed_at = datetime.now(timezone.utc)
            session.commit()
            return self._job(row)

    def list_recoverable_jobs(self, *, tenant_id: str | None = None) -> list[IngestionJob]:
        with Session(self.engine) as session:
            statement = select(IngestionJobRow).where(
                IngestionJobRow.status.in_(["queued", "running"])
            )
            if tenant_id is not None:
                statement = statement.where(IngestionJobRow.tenant_id == tenant_id)
            rows = session.scalars(statement.order_by(IngestionJobRow.created_at)).all()
            return [self._job(row) for row in rows]

    def request_cancel(self, *, tenant_id: str, job_id: UUID) -> IngestionJob:
        with Session(self.engine) as session:
            row = session.scalar(
                select(IngestionJobRow).where(
                    IngestionJobRow.tenant_id == tenant_id,
                    IngestionJobRow.id == str(job_id),
                )
            )
            if row is None:
                raise KeyError("ingestion job not found")
            if row.status == IngestionJobStatus.QUEUED.value:
                row.status = IngestionJobStatus.CANCELLED.value
                row.completed_at = datetime.now(timezone.utc)
            elif row.status == IngestionJobStatus.RUNNING.value:
                row.cancel_requested = True
            session.commit()
            return self._job(row)

    def fail_orphaned_jobs(self) -> int:
        """Mark running jobs from a crashed worker as safely failed on startup."""
        with Session(self.engine) as session:
            rows = session.scalars(
                select(IngestionJobRow).where(IngestionJobRow.status == "running")
            ).all()
            for row in rows:
                row.status = IngestionJobStatus.FAILED.value
                row.error = "worker restarted before job completion"
                row.completed_at = datetime.now(timezone.utc)
            session.commit()
            return len(rows)

    @staticmethod
    def _document(row: DocumentRow) -> DocumentRecord:
        return DocumentRecord(
            document_id=UUID(row.id), tenant_id=row.tenant_id,
            original_name=row.original_name, storage_name=row.storage_name,
            content_hash=row.content_hash, document_version=row.document_version,
            parser_version=row.parser_version, chunker_version=row.chunker_version,
            embedding_model=row.embedding_model, embedding_dimension=row.embedding_dimension,
            index_version=row.index_version, status=DocumentStatus(row.status),
            created_at=row.created_at,
        )

    @staticmethod
    def _job(row: IngestionJobRow) -> IngestionJob:
        return IngestionJob(
            job_id=UUID(row.id), tenant_id=row.tenant_id,
            idempotency_key=row.idempotency_key, status=IngestionJobStatus(row.status),
            created_at=row.created_at, started_at=row.started_at,
            completed_at=row.completed_at, error=row.error, result=row.result_ref,
        )
