from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter

from utils.file_handler import pdf_loader


class PdfLoaderCompatibilityTest(unittest.TestCase):
    def test_loads_pdf_created_by_patched_pypdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            with pdf_path.open("wb") as output:
                writer.write(output)

            documents = pdf_loader(str(pdf_path))

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].page_content, "")
        self.assertEqual(Path(documents[0].metadata["source"]), pdf_path)
        self.assertEqual(documents[0].metadata["page"], 0)


if __name__ == "__main__":
    unittest.main()
