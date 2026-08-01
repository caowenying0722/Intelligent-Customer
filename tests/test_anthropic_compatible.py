import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool

from model.anthropic_compatible import (
    AnthropicCompatibleChatModel,
    AnthropicCompatibleProviderError,
)


@tool
def get_weather(city: str) -> str:
    """Get the weather for a city."""
    return f"sunny in {city}"


class AnthropicCompatibleChatModelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.model = AnthropicCompatibleChatModel(
            model_name="test-model",
            base_url="https://example.test/anthropic",
            api_key="test-key",
        )

    def test_bind_tools_sends_anthropic_schema_and_parses_tool_use(self) -> None:
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_123",
                    "name": "get_weather",
                    "input": {"city": "深圳"},
                }
            ],
            "stop_reason": "tool_use",
        }

        with patch(
            "model.anthropic_compatible.requests.post", return_value=response
        ) as post:
            message = self.model.bind_tools([get_weather]).invoke(
                [HumanMessage(content="深圳天气如何？")]
            )

        payload = post.call_args.kwargs["json"]
        self.assertEqual(post.call_args.kwargs["timeout"], 120.0)
        self.assertIs(post.call_args.kwargs["verify"], True)
        self.assertEqual(payload["tools"][0]["name"], "get_weather")
        self.assertEqual(payload["tools"][0]["input_schema"]["required"], ["city"])
        self.assertEqual(
            message.tool_calls,
            [
                {
                    "name": "get_weather",
                    "args": {"city": "深圳"},
                    "id": "toolu_123",
                    "type": "tool_call",
                }
            ],
        )

    def test_convert_tool_result_message(self) -> None:
        from langchain_core.messages import AIMessage

        assistant = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "get_weather",
                    "args": {"city": "深圳"},
                    "id": "toolu_123",
                    "type": "tool_call",
                }
            ],
        )
        tool_result = ToolMessage(content="晴天", tool_call_id="toolu_123")

        _, messages = self.model._convert_messages(
            [HumanMessage(content="深圳天气如何？"), assistant, tool_result]
        )

        self.assertEqual(messages[1]["content"][0]["type"], "tool_use")
        self.assertEqual(messages[2]["content"][0]["type"], "tool_result")
        self.assertEqual(messages[2]["content"][0]["tool_use_id"], "toolu_123")

    def test_provider_error_does_not_expose_response_body(self) -> None:
        response = Mock()
        response.status_code = 429
        response.text = "sensitive provider response with prompt"
        response.headers = {"request-id": "req_123"}

        with patch("model.anthropic_compatible.requests.post", return_value=response):
            with self.assertRaises(AnthropicCompatibleProviderError) as raised:
                self.model.invoke([HumanMessage(content="hello")])

        message = str(raised.exception)
        self.assertIn("status=429", message)
        self.assertIn("request_id=req_123", message)
        self.assertNotIn("sensitive provider response", message)

    def test_invalid_json_and_success_metadata_do_not_store_raw_response(self) -> None:
        invalid_response = Mock()
        invalid_response.status_code = 200
        invalid_response.text = "secret body"
        invalid_response.json.side_effect = ValueError("secret body")
        with patch(
            "model.anthropic_compatible.requests.post", return_value=invalid_response
        ):
            with self.assertRaises(AnthropicCompatibleProviderError) as raised:
                self.model.invoke([HumanMessage(content="hello")])
        self.assertNotIn("secret body", str(raised.exception))

        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {
            "content": [{"type": "text", "text": "answer"}],
            "secret": "must not be retained",
        }
        with patch(
            "model.anthropic_compatible.requests.post", return_value=success_response
        ):
            result = self.model._generate([HumanMessage(content="hello")])

        self.assertNotIn("raw", result.llm_output or {})
        self.assertNotIn("must not be retained", str(result.llm_output))


if __name__ == "__main__":
    unittest.main()
