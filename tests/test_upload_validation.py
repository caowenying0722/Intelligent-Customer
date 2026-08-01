import pytest

from src.app.application.uploads import UploadValidationError, validate_upload


def test_upload_validation_returns_random_internal_name_and_digest() -> None:
    first = validate_upload("manual.txt", "hello".encode(), "text/plain")
    second = validate_upload("manual.txt", "hello".encode(), "text/plain")
    assert first.storage_name != second.storage_name
    assert first.extension == ".txt"
    assert len(first.sha256) == 64
    assert first.content == b"hello"


@pytest.mark.parametrize("filename", ["../evil.txt", "folder/evil.txt", "evil.exe", ""])
def test_upload_validation_rejects_untrusted_names(filename: str) -> None:
    with pytest.raises(UploadValidationError):
        validate_upload(filename, b"hello", "text/plain")


def test_upload_validation_rejects_size_mime_encoding_and_pdf_signature() -> None:
    with pytest.raises(UploadValidationError, match="maximum size"):
        validate_upload("a.txt", b"1234", "text/plain", max_bytes=3)
    with pytest.raises(UploadValidationError, match="MIME"):
        validate_upload("a.txt", b"hello", "application/pdf")
    with pytest.raises(UploadValidationError, match="UTF-8"):
        validate_upload("a.txt", b"\xff", "text/plain")
    with pytest.raises(UploadValidationError, match="signature"):
        validate_upload("a.pdf", b"not pdf", "application/pdf")


def test_upload_validation_accepts_pdf_signature_and_limits_text_chars() -> None:
    upload = validate_upload("manual.pdf", b"%PDF-1.7 fake", "application/pdf")
    assert upload.content_type == "application/pdf"
    with pytest.raises(UploadValidationError, match="characters"):
        validate_upload("a.txt", b"hello", "text/plain", max_text_chars=4)
