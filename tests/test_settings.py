from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from utils.settings import Settings


class SettingsTest(unittest.TestCase):
    def test_defaults_cover_future_api_and_agent_boundaries(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]

        self.assertEqual(settings.application_env, "development")
        self.assertEqual(settings.log_level, "INFO")
        self.assertEqual(settings.resolved_model_provider, "openai")
        self.assertEqual(settings.model_request_timeout_seconds, 120.0)
        self.assertEqual(settings.model_max_retries, 2)
        self.assertEqual(settings.agent_max_steps, 10)
        self.assertEqual(settings.agent_max_tool_calls, 5)
        self.assertEqual(settings.agent_max_input_chars, 4000)
        self.assertEqual(settings.agent_max_context_chars, 32000)
        self.assertEqual(settings.allowed_origins, ["http://localhost:8501"])
        self.assertEqual(settings.api_host, "127.0.0.1")
        self.assertEqual(settings.api_port, 8000)
        self.assertIsNone(settings.database_url)
        self.assertEqual(settings.database_pool_size, 5)
        self.assertEqual(settings.database_isolation_level, "READ COMMITTED")

    def test_database_url_accepts_supported_schemes_and_rejects_others(self) -> None:
        self.assertEqual(
            Settings.model_validate({"database_url": "sqlite:///app.db"}).database_url,
            "sqlite:///app.db",
        )
        self.assertEqual(
            Settings.model_validate(
                {"database_url": "postgresql+psycopg://user:pass@db/app"}
            ).database_url,
            "postgresql+psycopg://user:pass@db/app",
        )
        with self.assertRaisesRegex(ValidationError, "DATABASE_URL"):
            Settings.model_validate({"database_url": "redis://localhost/0"})

    def test_legacy_provider_alias_and_json_origins_are_supported(self) -> None:
        env = {
            "APP_ENV": "test",
            "LOG_LEVEL": "debug",
            "LLM__PROVIDER": "anthropic",
            "ALLOWED_ORIGINS": '["http://localhost:8501/", "https://example.test"]',
        }

        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]

        self.assertEqual(settings.application_env, "test")
        self.assertEqual(settings.log_level, "DEBUG")
        self.assertEqual(settings.resolved_model_provider, "anthropic")
        self.assertEqual(
            settings.allowed_origins,
            ["http://localhost:8501", "https://example.test"],
        )

    def test_anthropic_key_preserves_legacy_provider_inference(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_AUTH_TOKEN": "top-secret"}, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]

        self.assertEqual(settings.resolved_model_provider, "anthropic")
        self.assertEqual(settings.anthropic_api_key_value, "top-secret")
        self.assertNotIn("top-secret", repr(settings))

    def test_openai_compatible_key_priority_is_stable(self) -> None:
        env = {
            "OPENAI_API_KEY": "openai-key",
            "DEEPSEEK_API_KEY": "deepseek-key",
            "MOONSHOT_API_KEY": "moonshot-key",
        }

        with patch.dict(os.environ, env, clear=True):
            settings = Settings(_env_file=None)  # type: ignore[call-arg]

        self.assertEqual(settings.openai_compatible_api_key_value, "openai-key")

    def test_relative_ca_bundle_is_resolved_and_required_to_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = Path(temp_dir) / "private-ca.pem"
            bundle.write_text("test certificate placeholder", encoding="utf-8")
            settings = Settings.model_validate({"model_ca_bundle": bundle})

        self.assertEqual(settings.model_ca_bundle, bundle.resolve())

        with self.assertRaisesRegex(ValidationError, "MODEL_CA_BUNDLE"):
            Settings.model_validate({"model_ca_bundle": "missing-private-ca.pem"})

    def test_invalid_bounds_are_rejected(self) -> None:
        invalid_values = (
            {"model_request_timeout_seconds": 0},
            {"model_max_retries": 6},
            {"agent_max_steps": 0},
            {"agent_max_tool_calls": 0},
            {"agent_max_tool_calls": 21},
            {"agent_max_input_chars": 0},
            {"agent_max_context_chars": 0},
            {"api_port": 70000},
            {"database_pool_size": 0},
            {"database_pool_timeout_seconds": 0},
        )
        for values in invalid_values:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                Settings.model_validate(values)

    def test_production_rejects_wildcard_origin(self) -> None:
        with self.assertRaisesRegex(ValidationError, "Wildcard ALLOWED_ORIGINS"):
            Settings.model_validate(
                {"application_env": "production", "allowed_origins": ["*"]}
            )


if __name__ == "__main__":
    unittest.main()
