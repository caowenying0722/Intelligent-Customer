import pytest

from src.app.security.redaction import redact_text, text_metadata


def test_redact_text_removes_common_pii_and_credentials() -> None:
    value = "联系 user@example.com 或 13812345678，Bearer abc.def，sk-proj-123456789012345"

    redacted = redact_text(value)

    assert "user@example.com" not in redacted
    assert "13812345678" not in redacted
    assert "abc.def" not in redacted
    assert "sk-proj-123456789012345" not in redacted
    assert "<redacted-email>" in redacted
    assert "<redacted-phone>" in redacted
    assert "<redacted-token>" in redacted
    assert "<redacted-secret>" in redacted


def test_redact_text_is_bounded() -> None:
    result = redact_text("x" * 100, max_length=20)

    assert len(result) == 20
    assert result.endswith("...<truncated>")


def test_redaction_parameters_and_metadata_are_safe() -> None:
    with pytest.raises(ValueError, match="max_length"):
        redact_text("x", max_length=0)

    metadata = text_metadata("private prompt")

    assert metadata["length"] == len("private prompt")
    assert metadata["fingerprint"] != "private prompt"
    assert "private prompt" not in str(metadata)
