"""Atomic storage for already-validated untrusted uploads."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from src.app.application.uploads import ValidatedUpload


class UploadStorageError(RuntimeError):
    """A validated upload could not be safely persisted."""


class SecureUploadStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def persist(self, upload: ValidatedUpload) -> Path:
        """Write bytes atomically beneath root and return the internal path."""
        destination = (self.root / upload.storage_name).resolve()
        if destination.parent != self.root:
            raise UploadStorageError("upload storage path escaped configured root")
        if destination.exists():
            raise UploadStorageError("upload storage name already exists")
        temporary = self.root / f".{uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as handle:
                handle.write(upload.content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise UploadStorageError("upload could not be persisted") from exc
        return destination

    def remove(self, storage_name: str) -> None:
        """Remove only a direct child internal name, never an arbitrary path."""
        destination = (self.root / storage_name).resolve()
        if destination.parent != self.root:
            raise UploadStorageError("upload storage path escaped configured root")
        try:
            destination.unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise UploadStorageError("upload could not be removed") from exc
