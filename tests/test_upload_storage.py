import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from src.app.application.upload_storage import SecureUploadStorage, UploadStorageError
from src.app.application.uploads import validate_upload


def test_secure_storage_persists_atomically_and_removes_internal_file() -> None:
    root = Path("output") / f"upload-storage-test-{uuid4().hex}"
    storage = SecureUploadStorage(root)
    try:
        upload = validate_upload("manual.txt", b"payload", "text/plain")
        path = storage.persist(upload)
        assert path.parent == root.resolve()
        assert path.read_bytes() == b"payload"
        storage.remove(upload.storage_name)
        assert not path.exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_secure_storage_rejects_path_escape_for_removal() -> None:
    root = Path("output") / f"upload-storage-test-{uuid4().hex}"
    storage = SecureUploadStorage(root)
    try:
        with pytest.raises(UploadStorageError, match="escaped"):
            storage.remove("../outside.txt")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_secure_storage_does_not_overwrite_existing_internal_name() -> None:
    root = Path("output") / f"upload-storage-test-{uuid4().hex}"
    storage = SecureUploadStorage(root)
    try:
        upload = validate_upload("manual.txt", b"one", "text/plain")
        storage.persist(upload)
        with pytest.raises(UploadStorageError):
            storage.persist(upload)
    finally:
        shutil.rmtree(root, ignore_errors=True)
