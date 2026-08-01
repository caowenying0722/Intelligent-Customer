"""Validate untrusted document uploads before background ingestion."""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import PurePath
from uuid import uuid4


class UploadValidationError(ValueError):
    """The upload does not satisfy the safe ingestion boundary."""


@dataclass(frozen=True)
class ValidatedUpload:
    original_name: str
    extension: str
    content_type: str
    size_bytes: int
    sha256: str
    storage_name: str
    content: bytes


def validate_upload(
    filename: str,
    content: bytes,
    content_type: str | None,
    *,
    max_bytes: int = 10 * 1024 * 1024,
    max_text_chars: int = 1_000_000,
) -> ValidatedUpload:
    """Validate content and return a random internal name; never writes files."""
    if max_bytes < 1 or max_text_chars < 1:
        raise ValueError("upload limits must be positive")
    if not filename or "\x00" in filename:
        raise UploadValidationError("invalid filename")
    path = PurePath(filename)
    if len(path.parts) != 1 or path.name != filename or filename in {".", ".."}:
        raise UploadValidationError("path traversal is not allowed")
    extension = path.suffix.lower()
    if extension not in {".txt", ".pdf"}:
        raise UploadValidationError("unsupported file extension")
    if len(content) > max_bytes:
        raise UploadValidationError("file exceeds maximum size")
    declared = (content_type or mimetypes.guess_type(filename)[0] or "").lower()
    if extension == ".pdf":
        if declared not in {"application/pdf", "application/octet-stream"}:
            raise UploadValidationError("PDF MIME type is invalid")
        if not content.startswith(b"%PDF-"):
            raise UploadValidationError("PDF signature is invalid")
        normalized_type = "application/pdf"
    else:
        if declared and not (declared == "text/plain" or declared.startswith("text/")):
            raise UploadValidationError("text MIME type is invalid")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UploadValidationError("text upload must be UTF-8") from exc
        if len(text) > max_text_chars:
            raise UploadValidationError("text upload exceeds maximum characters")
        normalized_type = "text/plain"
    digest = hashlib.sha256(content).hexdigest()
    return ValidatedUpload(
        original_name=filename,
        extension=extension,
        content_type=normalized_type,
        size_bytes=len(content),
        sha256=digest,
        storage_name=f"{uuid4().hex}{extension}",
        content=content,
    )
