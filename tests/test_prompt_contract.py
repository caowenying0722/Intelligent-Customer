from __future__ import annotations

from pathlib import Path

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "main_prompt.txt"


def test_main_prompt_does_not_request_hidden_chain_of_thought() -> None:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "真实的自然语言思考过程" not in prompt
    assert "真实思考过程" not in prompt
    assert "隐藏推理" in prompt
    assert "简短的进度说明" in prompt


def test_main_prompt_keeps_tool_and_final_answer_contracts() -> None:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "直接触发工具调用" in prompt
    assert "工具入参精准匹配需求" in prompt
    assert "生成最终自然语言回答" in prompt
