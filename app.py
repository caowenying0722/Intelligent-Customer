from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Protocol, cast

STREAMLIT_HISTORY_MAX_MESSAGES = 20
STREAMLIT_HISTORY_MAX_CHARS = 8_000


class StreamAgent(Protocol):
    def execute_stream(self, query: str) -> Iterable[str]: ...


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


def capture_stream(chunks: Iterable[str], cache: list[str]) -> Iterator[str]:
    """Forward complete Agent chunks without per-character blocking sleeps."""

    for chunk in chunks:
        cache.append(chunk)
        yield chunk


def main() -> None:
    import warnings

    warnings.filterwarnings("ignore", message=".*torch.classes.*")

    import streamlit as st

    from agent.react_agent import ReactAgent

    st.title("智扫通机器人智能客服")
    st.divider()

    if "agent" not in st.session_state:
        st.session_state["agent"] = ReactAgent()

    if "message" not in st.session_state:
        st.session_state["message"] = []

    for message in st.session_state["message"]:
        st.chat_message(message["role"]).write(message["content"])

    prompt = st.chat_input()

    if prompt:
        history = bounded_history(st.session_state["message"])
        st.chat_message("user").write(prompt)
        st.session_state["message"].append({"role": "user", "content": prompt})

        response_messages: list[str] = []
        with st.spinner("智能客服思考中..."):
            res_stream = stream_agent_response(
                st.session_state["agent"], prompt, history
            )

            st.chat_message("assistant").write_stream(
                capture_stream(res_stream, response_messages)
            )
            st.session_state["message"].append(
                {"role": "assistant", "content": "".join(response_messages).strip()}
            )
            st.rerun()


if __name__ == "__main__":
    main()
