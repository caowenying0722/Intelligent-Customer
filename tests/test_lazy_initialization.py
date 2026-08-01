from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LazyInitializationTest(unittest.TestCase):
    def run_isolated_import(self, source: str) -> None:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-c", source],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )

    def test_app_import_does_not_load_agent_model_or_rag_modules(self) -> None:
        self.run_isolated_import(
            """
import sys
import app

forbidden = {
    "agent.react_agent",
    "model.factory",
    "rag.rag_service",
    "rag.vector_store",
}
loaded = sorted(forbidden.intersection(sys.modules))
assert not loaded, f"application import eagerly loaded: {loaded}"
"""
        )

    def test_model_factory_import_keeps_model_caches_empty(self) -> None:
        self.run_isolated_import(
            """
import sys
import model.factory as factory

assert factory.get_chat_model.cache_info().currsize == 0
assert factory.get_embedding_model.cache_info().currsize == 0
assert "utils.config_handler" not in sys.modules
"""
        )

    def test_agent_tools_import_does_not_load_rag_modules(self) -> None:
        self.run_isolated_import(
            """
import sys
import agent.tools.agent_tools

forbidden = {"rag.rag_service", "rag.vector_store"}
loaded = sorted(forbidden.intersection(sys.modules))
assert not loaded, f"agent tools import eagerly loaded: {loaded}"
"""
        )

    def test_chat_model_is_created_once_on_first_explicit_access(self) -> None:
        from model import factory

        factory.get_chat_model.cache_clear()
        sentinel = object()
        with patch.object(
            factory.ChatModelFactory,
            "generator",
            return_value=sentinel,
        ) as generator:
            self.assertIs(factory.get_chat_model(), sentinel)
            self.assertIs(factory.get_chat_model(), sentinel)

        generator.assert_called_once_with()
        factory.get_chat_model.cache_clear()

    def test_rag_service_is_created_once_on_first_tool_access(self) -> None:
        from agent.tools import agent_tools

        agent_tools.get_rag_service.cache_clear()
        sentinel = object()
        with patch(
            "rag.rag_service.RagSummarizeService",
            return_value=sentinel,
        ) as service_factory:
            self.assertIs(agent_tools.get_rag_service(), sentinel)
            self.assertIs(agent_tools.get_rag_service(), sentinel)

        service_factory.assert_called_once_with()
        agent_tools.get_rag_service.cache_clear()


if __name__ == "__main__":
    unittest.main()
