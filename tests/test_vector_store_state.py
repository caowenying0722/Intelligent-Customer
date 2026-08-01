import tempfile
from pathlib import Path

from rag.vector_store import DocumentLoadSummary, append_md5_record


def test_md5_record_is_durable_and_append_only() -> None:
    with tempfile.TemporaryDirectory(
        dir=Path.cwd(), prefix=".vector-state-test-"
    ) as root:
        marker = Path(root) / "state" / "md5.txt"

        append_md5_record(str(marker), "a" * 32)
        append_md5_record(str(marker), "b" * 32)

        assert marker.read_text(encoding="utf-8").splitlines() == [
            "a" * 32,
            "b" * 32,
        ]


def test_document_load_summary_has_bounded_fields() -> None:
    summary = DocumentLoadSummary(
        loaded=1,
        skipped=2,
        failed=1,
        failure_types=("OSError",),
    )

    assert summary.loaded == 1
    assert summary.skipped == 2
    assert summary.failed == 1
    assert summary.failure_types == ("OSError",)
