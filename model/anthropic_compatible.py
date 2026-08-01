from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import requests
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool


class AnthropicCompatibleChatModel(BaseChatModel):
    model_name: str
    base_url: str
    api_key: str
    max_tokens: int = 4096
    temperature: float = 0.0
    timeout: int = 120

    @property
    def _llm_type(self) -> str:
        return "anthropic-compatible"

    def _messages_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/messages"):
            return base
        if base.endswith("/v1"):
            return f"{base}/messages"
        return f"{base}/v1/messages"

    @staticmethod
    def _content_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            return "\n".join(part for part in parts if part)
        return str(content)

    @staticmethod
    def _merge_message(
        messages: list[dict[str, Any]],
        role: str,
        content: str | list[dict[str, Any]],
    ) -> None:
        """Append a message, combining adjacent messages with the same role."""

        if not messages or messages[-1]["role"] != role:
            messages.append({"role": role, "content": content})
            return

        def as_blocks(value: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
            if isinstance(value, list):
                return value
            return [{"type": "text", "text": value}]

        messages[-1]["content"] = as_blocks(messages[-1]["content"]) + as_blocks(content)

    def _convert_messages(self, messages: list[BaseMessage]) -> tuple[str | None, list[dict[str, Any]]]:
        system_parts: list[str] = []
        converted: list[dict[str, Any]] = []

        for message in messages:
            content = self._content_to_text(message.content)
            if isinstance(message, SystemMessage):
                system_parts.append(content)
            elif isinstance(message, AIMessage):
                raw_content = message.additional_kwargs.get("anthropic_content")
                if isinstance(raw_content, list):
                    assistant_content: str | list[dict[str, Any]] = raw_content
                elif message.tool_calls:
                    blocks: list[dict[str, Any]] = []
                    if content:
                        blocks.append({"type": "text", "text": content})
                    blocks.extend(
                        {
                            "type": "tool_use",
                            "id": tool_call["id"],
                            "name": tool_call["name"],
                            "input": tool_call["args"],
                        }
                        for tool_call in message.tool_calls
                    )
                    assistant_content = blocks
                else:
                    assistant_content = content
                self._merge_message(converted, "assistant", assistant_content)
            elif isinstance(message, ToolMessage):
                tool_result = {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": content,
                }
                self._merge_message(converted, "user", [tool_result])
            elif isinstance(message, HumanMessage):
                self._merge_message(converted, "user", content)
            else:
                self._merge_message(converted, "user", content)

        system = "\n".join(part for part in system_parts if part) or None
        return system, converted

    @staticmethod
    def _tool_args(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        return {}

    @classmethod
    def _extract_response(cls, data: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        if isinstance(data.get("content"), list):
            for item in data["content"]:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    text_parts.append(str(item.get("text", "")))
                elif item.get("type") == "tool_use":
                    tool_calls.append(
                        {
                            "name": str(item.get("name", "")),
                            "args": cls._tool_args(item.get("input", {})),
                            "id": str(item.get("id", "")),
                            "type": "tool_call",
                        }
                    )

        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            if message.get("content"):
                text_parts.append(str(message["content"]))
            for tool_call in message.get("tool_calls", []):
                function = tool_call.get("function", {})
                tool_calls.append(
                    {
                        "name": str(function.get("name", "")),
                        "args": cls._tool_args(function.get("arguments", {})),
                        "id": str(tool_call.get("id", "")),
                        "type": "tool_call",
                    }
                )

        if not text_parts and not tool_calls and data.get("content"):
            text_parts.append(str(data["content"]))

        return "\n".join(part for part in text_parts if part), tool_calls

    @staticmethod
    def _format_tool(tool: Any) -> dict[str, Any]:
        if isinstance(tool, dict) and {"name", "input_schema"}.issubset(tool):
            return tool

        openai_tool = convert_to_openai_tool(tool)
        function = openai_tool["function"]
        return {
            "name": function["name"],
            "description": function.get("description", ""),
            "input_schema": function.get(
                "parameters",
                {"type": "object", "properties": {}},
            ),
        }

    @staticmethod
    def _format_tool_choice(tool_choice: Any) -> dict[str, Any] | None:
        if tool_choice is None:
            return None
        if isinstance(tool_choice, dict):
            return tool_choice
        if tool_choice in {"auto", "any", "none"}:
            return {"type": tool_choice}
        return {"type": "tool", "name": str(tool_choice)}

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: Any | None = None,
        **kwargs: Any,
    ) -> Any:
        formatted_tools = [self._format_tool(tool) for tool in tools]
        formatted_choice = self._format_tool_choice(tool_choice)
        if formatted_choice is not None:
            kwargs["tool_choice"] = formatted_choice
        return self.bind(tools=formatted_tools, **kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        system, converted_messages = self._convert_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "temperature": kwargs.get("temperature", self.temperature),
            "messages": converted_messages,
        }
        if system:
            payload["system"] = system
        if stop:
            payload["stop_sequences"] = stop
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]
        if kwargs.get("tool_choice"):
            payload["tool_choice"] = kwargs["tool_choice"]

        headers = {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": self.api_key,
            "authorization": f"Bearer {self.api_key}",
        }
        response = requests.post(
            self._messages_url(),
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Anthropic-compatible chat request failed: {response.status_code} {response.text}")

        data = response.json()
        text, tool_calls = self._extract_response(data)
        additional_kwargs: dict[str, Any] = {}
        if isinstance(data.get("content"), list):
            additional_kwargs["anthropic_content"] = data["content"]
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content=text,
                        tool_calls=tool_calls,
                        additional_kwargs=additional_kwargs,
                    )
                )
            ],
            llm_output={"model": self.model_name, "raw": data},
        )
