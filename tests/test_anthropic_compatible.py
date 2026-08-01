import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool

from model.anthropic_compatible import AnthropicCompatibleChatModel


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


if __name__ == "__main__":
    unittest.main()
