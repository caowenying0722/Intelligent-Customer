from __future__ import annotations

import os
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from model.factory import ChatModelFactory
from model.runtime_config import ModelRuntimeConfig


class ModelRuntimeConfigTest(unittest.TestCase):
    def test_defaults_are_bounded_and_verify_tls(self) -> None:
        config = ModelRuntimeConfig.from_env({})

        self.assertEqual(config.request_timeout_seconds, 120.0)
        self.assertEqual(config.max_retries, 2)
        self.assertIs(config.requests_verify, True)

    def test_custom_ca_bundle_is_resolved_from_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "private-ca.pem"
            bundle.write_text("test certificate placeholder", encoding="utf-8")

            config = ModelRuntimeConfig.from_env(
                {
                    "MODEL_REQUEST_TIMEOUT_SECONDS": "15.5",
                    "MODEL_MAX_RETRIES": "3",
                    "MODEL_CA_BUNDLE": bundle.name,
                },
                project_root=root,
            )

        self.assertEqual(config.request_timeout_seconds, 15.5)
        self.assertEqual(config.max_retries, 3)
        self.assertEqual(config.ca_bundle, bundle.resolve())
        self.assertEqual(config.requests_verify, str(bundle.resolve()))

    def test_invalid_timeout_is_rejected(self) -> None:
        for value in ("not-a-number", "0", "601"):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "MODEL_REQUEST_TIMEOUT_SECONDS"),
            ):
                ModelRuntimeConfig.from_env({"MODEL_REQUEST_TIMEOUT_SECONDS": value})

    def test_invalid_retry_limit_is_rejected(self) -> None:
        for value in ("not-an-integer", "-1", "6"):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "MODEL_MAX_RETRIES"),
            ):
                ModelRuntimeConfig.from_env({"MODEL_MAX_RETRIES": value})

    def test_missing_ca_bundle_is_rejected(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            self.assertRaisesRegex(ValueError, "MODEL_CA_BUNDLE"),
        ):
            ModelRuntimeConfig.from_env(
                {"MODEL_CA_BUNDLE": "missing.pem"},
                project_root=Path(temp_dir),
            )

    def test_openai_factory_passes_timeout_and_retry_limit(self) -> None:
        env = {
            "LLM__PROVIDER": "openai",
            "OPENAI_API_KEY": "dummy",
            "MODEL_REQUEST_TIMEOUT_SECONDS": "12.5",
            "MODEL_MAX_RETRIES": "4",
        }

        with (
            patch.dict(os.environ, env, clear=True),
            patch("model.factory.ChatOpenAI") as chat_openai,
        ):
            ChatModelFactory().generator()

        kwargs = chat_openai.call_args.kwargs
        self.assertEqual(kwargs["request_timeout"], 12.5)
        self.assertEqual(kwargs["max_retries"], 4)
        self.assertNotIn("http_client", kwargs)
        self.assertNotIn("http_async_client", kwargs)

    def test_openai_factory_builds_ca_verified_http_clients(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = Path(temp_dir) / "private-ca.pem"
            bundle.write_text("test certificate placeholder", encoding="utf-8")
            env = {
                "LLM__PROVIDER": "openai",
                "OPENAI_API_KEY": "dummy",
                "MODEL_REQUEST_TIMEOUT_SECONDS": "20",
                "MODEL_CA_BUNDLE": str(bundle),
            }

            with (
                patch.dict(os.environ, env, clear=True),
                patch("model.factory.ChatOpenAI") as chat_openai,
                patch("model.factory.httpx.Client") as sync_client,
                patch("model.factory.httpx.AsyncClient") as async_client,
                patch("model.factory.ssl.create_default_context") as create_context,
            ):
                ChatModelFactory().generator()

        create_context.assert_called_once_with(cafile=str(bundle.resolve()))
        sync_client.assert_called_once_with(
            verify=create_context.return_value, timeout=20.0
        )
        async_client.assert_called_once_with(
            verify=create_context.return_value, timeout=20.0
        )
        self.assertIs(
            chat_openai.call_args.kwargs["http_client"], sync_client.return_value
        )
        self.assertIs(
            chat_openai.call_args.kwargs["http_async_client"],
            async_client.return_value,
        )

    def test_anthropic_factory_passes_tls_and_timeout_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = Path(temp_dir) / "private-ca.pem"
            bundle.write_text("test certificate placeholder", encoding="utf-8")
            env = {
                "LLM__PROVIDER": "anthropic",
                "ANTHROPIC_AUTH_TOKEN": "dummy",
                "MODEL_REQUEST_TIMEOUT_SECONDS": "18",
                "MODEL_CA_BUNDLE": str(bundle),
            }

            with (
                patch.dict(os.environ, env, clear=True),
                patch("model.factory.AnthropicCompatibleChatModel") as anthropic_model,
            ):
                ChatModelFactory().generator()

        kwargs = anthropic_model.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 18.0)
        self.assertEqual(kwargs["verify"], str(bundle.resolve()))

    def test_factory_does_not_replace_global_tls_context(self) -> None:
        self.assertIs(ssl._create_default_https_context, ssl.create_default_context)


if __name__ == "__main__":
    unittest.main()
