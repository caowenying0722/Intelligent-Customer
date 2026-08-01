from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest

from app import (
    StreamlitAPIError,
    bounded_history,
    capture_stream,
    iter_sse_tokens,
    stream_agent_response,
)
from utils.settings import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StreamlitAppCompatibilityTest(unittest.TestCase):
    def test_sse_parser_forwards_tokens_and_captures_conversation(self) -> None:
        conversation_ids: list[str] = []
        lines = [
            'data: {"type":"metadata","conversation_id":"conversation-1"}',
            "",
            'data: {"type":"token","text":"hello"}',
            'data: {"type":"completed"}',
        ]

        self.assertEqual(list(iter_sse_tokens(lines, conversation_ids)), ["hello"])
        self.assertEqual(conversation_ids, ["conversation-1"])

    def test_sse_parser_maps_unknown_error_without_body_details(self) -> None:
        with self.assertRaises(StreamlitAPIError) as context:
            list(iter_sse_tokens(['data: {"type":"error","code": {}}']))

        self.assertEqual(context.exception.code, "stream_http_failed")
        self.assertNotIn("{}", str(context.exception))

    @patch("httpx.Client")
    def test_http_sse_client_uses_bounded_timeout_and_conversation(
        self, client_type: MagicMock
    ) -> None:
        client = MagicMock()
        client_type.return_value.__enter__.return_value = client
        response = MagicMock(status_code=200)
        response.iter_lines.return_value = [
            'data: {"type":"metadata","conversation_id":"conversation-2"}',
            'data: {"type":"token","text":"answer"}',
        ]
        client.stream.return_value.__enter__.return_value = response
        conversation_ids: list[str] = []

        from app import stream_http_sse

        self.assertEqual(
            list(
                stream_http_sse(
                    "http://localhost:8000/",
                    "question",
                    conversation_id="conversation-1",
                    conversation_id_sink=conversation_ids,
                    timeout_seconds=3,
                )
            ),
            ["answer"],
        )
        client_type.assert_called_once_with(base_url="http://localhost:8000", timeout=3)
        client.stream.assert_called_once_with(
            "POST",
            "/api/v1/chat/stream",
            json={"message": "question", "conversation_id": "conversation-1"},
        )
        self.assertEqual(conversation_ids, ["conversation-2"])

    def test_streamlit_http_settings_are_validated_and_bounded(self) -> None:
        settings = Settings.model_validate(
            {
                "streamlit_mode": "http",
                "streamlit_api_url": "http://localhost:8000/",
                "streamlit_api_timeout_seconds": 4,
            }
        )

        self.assertEqual(settings.streamlit_api_url, "http://localhost:8000")
        self.assertEqual(settings.streamlit_api_timeout_seconds, 4)
        with self.assertRaises(ValueError):
            Settings.model_validate({"streamlit_api_url": "file:///tmp/api"})

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
