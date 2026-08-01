from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from utils.env_loader import clean_env_value, load_env_file


def load_project_env(project_root: str | Path | None = None) -> None:
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]
    load_env_file(root / ".env")


def judge_llm_status(rag_config: dict[str, Any], project_root: str | Path | None = None) -> dict[str, Any]:
    load_project_env(project_root)

    provider_env = os.environ.get("LLM__PROVIDER", "").lower()
    anthropic_key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
    anthropic_base_url = clean_env_value(os.environ.get("ANTHROPIC_BASE_URL", ""))
    anthropic_model = (
        os.environ.get("ANTHROPIC_MODEL")
        or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
        or os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")
        or os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL")
    )

    if provider_env == "anthropic" or anthropic_key:
        accepted_keys = ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"]
        return {
            "ok": bool(anthropic_key),
            "provider": "anthropic-compatible",
            "chat_model_name": anthropic_model or rag_config.get("chat_model_name"),
            "chat_base_url": anthropic_base_url or "https://api.anthropic.com",
            "accepted_keys": accepted_keys,
            "present_keys": [key for key in accepted_keys if os.environ.get(key)],
        }

    base_url = str(rag_config.get("chat_base_url", ""))
    provider = "openai-compatible"
    accepted_keys = ["OPENAI_API_KEY"]

    if "deepseek" in base_url:
        provider = "deepseek"
        accepted_keys = ["DEEPSEEK_API_KEY", "OPENAI_API_KEY"]
    elif "moonshot" in base_url or "kimi" in base_url:
        provider = "moonshot"
        accepted_keys = ["MOONSHOT_API_KEY", "OPENAI_API_KEY"]

    return {
        "ok": any(os.environ.get(key) for key in accepted_keys),
        "provider": provider,
        "chat_model_name": rag_config.get("chat_model_name"),
        "chat_base_url": base_url,
        "accepted_keys": accepted_keys,
        "present_keys": [key for key in accepted_keys if os.environ.get(key)],
    }
