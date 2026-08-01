import json
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Protocol, cast

STREAMLIT_HISTORY_MAX_MESSAGES = 20
STREAMLIT_HISTORY_MAX_CHARS = 8_000


class StreamAgent(Protocol):
    def execute_stream(self, query: str) -> Iterable[str]: ...


class StreamlitAPIError(RuntimeError):
    """Stable, non-sensitive error for the optional HTTP client mode."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_STREAM_ERROR_CODES = {
    "chat_timeout",
    "chat_unavailable",
    "chat_failed",
    "provider_unavailable",
    "rate_limited",
}


def bounded_history(
    messages: Iterable[Mapping[str, str]],
    *,
    max_messages: int = STREAMLIT_HISTORY_MAX_MESSAGES,
    max_chars: int = STREAMLIT_HISTORY_MAX_CHARS,
) -> list[tuple[str, str]]:
    """Convert displayed messages to the bounded Agent history contract."""

    if max_messages <= 0 or max_chars <= 0:
        return []
    selected = list(messages)[-max_messages:]
    bounded: list[tuple[str, str]] = []
    total_chars = 0
    for message in reversed(selected):
        role = message.get("role", "")
        content = message.get("content", "")
        if role not in {"user", "assistant"} or not content:
            continue
        content = content[:max_chars]
        if total_chars + len(content) > max_chars:
            break
        bounded.append((role, content))
        total_chars += len(content)
    bounded.reverse()
    return bounded


def stream_agent_response(
    agent: StreamAgent,
    prompt: str,
    history: list[tuple[str, str]],
) -> Iterable[str]:
    """Use a history-aware stream when available, retaining legacy compatibility."""

    history_runner = cast(
        Callable[[str, list[tuple[str, str]]], Iterable[str]] | None,
        getattr(agent, "stream_with_history", None),
    )
    if history and callable(history_runner):
        return history_runner(prompt, history)
    return agent.execute_stream(prompt)


def iter_sse_tokens(
    lines: Iterable[str], conversation_id_sink: list[str] | None = None
) -> Iterator[str]:
    """Parse the API SSE contract without exposing event error details."""

    for line in lines:
        if not line.startswith("data:"):
            continue
        raw_event = line[5:].strip()
        if not raw_event or raw_event == "[DONE]":
            continue
        try:
            event = json.loads(raw_event)
        except json.JSONDecodeError as exc:
            raise StreamlitAPIError("stream_http_invalid_event") from exc
        if not isinstance(event, dict):
            raise StreamlitAPIError("stream_http_invalid_event")
        event_type = event.get("type")
        if event_type == "metadata":
            conversation_id = event.get("conversation_id")
            if conversation_id_sink is not None and isinstance(conversation_id, str):
                conversation_id_sink.append(conversation_id)
        elif event_type == "token":
            text = event.get("text")
            if isinstance(text, str):
                yield text
        elif event_type == "error":
            code = event.get("code")
            safe_code = (
                code
                if isinstance(code, str) and code in _STREAM_ERROR_CODES
                else "stream_http_failed"
            )
            raise StreamlitAPIError(safe_code)


def stream_http_sse(
    base_url: str,
    prompt: str,
    *,
    conversation_id: str | None = None,
    conversation_id_sink: list[str] | None = None,
    timeout_seconds: float = 30.0,
) -> Iterator[str]:
    """Call the FastAPI SSE endpoint with a bounded timeout."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    import httpx

    payload: dict[str, str] = {"message": prompt}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    try:
        with httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout_seconds
        ) as client:
            with client.stream("POST", "/api/v1/chat/stream", json=payload) as response:
                if response.status_code >= 400:
                    raise StreamlitAPIError("stream_http_failed")
                yield from iter_sse_tokens(response.iter_lines(), conversation_id_sink)
    except StreamlitAPIError:
        raise
    except httpx.TimeoutException as exc:
        raise StreamlitAPIError("stream_http_timeout") from exc
    except httpx.HTTPError as exc:
        raise StreamlitAPIError("stream_http_unavailable") from exc


def capture_stream(chunks: Iterable[str], cache: list[str]) -> Iterator[str]:
    """Forward complete Agent chunks without per-character blocking sleeps."""

    for chunk in chunks:
        cache.append(chunk)
        yield chunk


def main() -> None:
    import warnings

    warnings.filterwarnings("ignore", message=".*torch.classes.*")

    import streamlit as st

    from utils.settings import get_settings

    settings = get_settings()

    st.title("智扫通机器人智能客服")
    st.divider()

    if settings.streamlit_mode == "local" and "agent" not in st.session_state:
        from agent.react_agent import ReactAgent

        st.session_state["agent"] = ReactAgent()

    if "message" not in st.session_state:
        st.session_state["message"] = []
    if "conversation_id" not in st.session_state:
        st.session_state["conversation_id"] = None

    for message in st.session_state["message"]:
        st.chat_message(message["role"]).write(message["content"])

    prompt = st.chat_input()

    if prompt:
        history = bounded_history(st.session_state["message"])
        st.chat_message("user").write(prompt)
        st.session_state["message"].append({"role": "user", "content": prompt})

        response_messages: list[str] = []
        with st.spinner("智能客服思考中..."):
            conversation_id_sink: list[str] = []
            res_stream: Iterable[str]
            if settings.streamlit_mode == "http":
                res_stream = stream_http_sse(
                    settings.streamlit_api_url,
                    prompt,
                    conversation_id=st.session_state["conversation_id"],
                    conversation_id_sink=conversation_id_sink,
                    timeout_seconds=settings.streamlit_api_timeout_seconds,
                )
            else:
                res_stream = stream_agent_response(
                    st.session_state["agent"], prompt, history
                )

            try:
                st.chat_message("assistant").write_stream(
                    capture_stream(res_stream, response_messages)
                )
            except StreamlitAPIError as exc:
                st.error(f"服务暂时不可用（{exc.code}）")
            if conversation_id_sink:
                st.session_state["conversation_id"] = conversation_id_sink[-1]
            st.session_state["message"].append(
                {"role": "assistant", "content": "".join(response_messages).strip()}
            )
            st.rerun()


if __name__ == "__main__":
    main()
