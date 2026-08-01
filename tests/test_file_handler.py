from __future__ import annotations

import tempfile
from pathlib import Path

from utils.file_handler import listdir_with_allowed_type


def test_invalid_directory_returns_empty_tuple() -> None:
    with tempfile.TemporaryDirectory(
        dir=Path.cwd(), prefix=".file-handler-test-"
    ) as root:
        result = listdir_with_allowed_type(str(Path(root) / "missing"), ("txt", "pdf"))

    assert result == ()


def test_directory_listing_only_returns_allowed_files() -> None:
    with tempfile.TemporaryDirectory(
        dir=Path.cwd(), prefix=".file-handler-test-"
    ) as root:
        root_path = Path(root)
        txt_file = root_path / "guide.txt"
        pdf_file = root_path / "manual.pdf"
        ignored_file = root_path / "notes.md"
        for file_path in (txt_file, pdf_file, ignored_file):
            file_path.write_text("content", encoding="utf-8")

        result = listdir_with_allowed_type(str(root_path), ("txt", "pdf"))

    assert result == (str(txt_file), str(pdf_file))
