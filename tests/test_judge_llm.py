from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from utils.judge_llm import judge_llm_status


class JudgeLlmStatusTest(unittest.TestCase):
    def test_anthropic_compatible_env_is_detected(self) -> None:
        env = {
            "LLM__PROVIDER": "anthropic",
            "ANTHROPIC_AUTH_TOKEN": "dummy",
            "ANTHROPIC_BASE_URL": "[https://api.deepseek.com/anthropic](https://api.deepseek.com/anthropic)",
            "ANTHROPIC_MODEL": "deepseek-v4-flash",
        }
        with tempfile.TemporaryDirectory() as project_root, patch.dict(os.environ, env, clear=True):
            status = judge_llm_status({}, project_root=project_root)

        self.assertTrue(status["ok"])
        self.assertEqual(status["provider"], "anthropic-compatible")
        self.assertEqual(status["chat_base_url"], "https://api.deepseek.com/anthropic")
        self.assertEqual(status["present_keys"], ["ANTHROPIC_AUTH_TOKEN"])

    def test_openai_compatible_key_missing(self) -> None:
        with tempfile.TemporaryDirectory() as project_root, patch.dict(os.environ, {}, clear=True):
            status = judge_llm_status(
                {"chat_model_name": "deepseek-chat", "chat_base_url": "https://api.deepseek.com/v1"},
                project_root=project_root,
            )

        self.assertFalse(status["ok"])
        self.assertEqual(status["provider"], "deepseek")
        self.assertEqual(status["present_keys"], [])


if __name__ == "__main__":
    unittest.main()
