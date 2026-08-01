from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app import capture_stream

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StreamlitAppCompatibilityTest(unittest.TestCase):
    def test_capture_stream_forwards_chunks_without_rechunking(self) -> None:
        cached: list[str] = []

        self.assertEqual(
            list(capture_stream(["first", "second"], cached)),
            [
                "first",
                "second",
            ],
        )
        self.assertEqual(cached, ["first", "second"])

    def test_home_page_starts_without_loading_external_models(self) -> None:
        app = AppTest.from_file(PROJECT_ROOT / "app.py", default_timeout=30).run()

        self.assertEqual(list(app.exception), [])
        self.assertEqual(app.title[0].value, "智扫通机器人智能客服")
        self.assertEqual(len(app.chat_input), 1)


if __name__ == "__main__":
    unittest.main()
