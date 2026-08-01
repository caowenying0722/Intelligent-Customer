from __future__ import annotations

import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app import bounded_history, capture_stream, stream_agent_response

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StreamlitAppCompatibilityTest(unittest.TestCase):
    def test_bounded_history_preserves_recent_context_with_character_limit(
        self,
    ) -> None:
        messages = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "middle"},
            {"role": "user", "content": "latest"},
        ]

        self.assertEqual(
            bounded_history(messages, max_messages=2, max_chars=12),
            [("assistant", "middle"), ("user", "latest")],
        )

    def test_stream_agent_response_uses_history_aware_agent_when_available(
        self,
    ) -> None:
        class HistoryAgent:
            def execute_stream(self, query: str) -> list[str]:
                return [f"legacy:{query}"]

            def stream_with_history(
                self, query: str, history: list[tuple[str, str]]
            ) -> list[str]:
                return [f"history:{len(history)}:{query}"]

        agent = HistoryAgent()

        self.assertEqual(
            list(stream_agent_response(agent, "new", [("user", "old")])),
            ["history:1:new"],
        )
        self.assertEqual(list(stream_agent_response(agent, "new", [])), ["legacy:new"])

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
