from __future__ import annotations

import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from model.factory import ChatModelFactory
from model.runtime_config import ModelRuntimeConfig
from utils.settings import Settings


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
        settings = Settings.model_validate(
            {
                "model_provider": "openai",
                "openai_api_key": "dummy",
                "model_request_timeout_seconds": 12.5,
                "model_max_retries": 4,
            }
        )

        with patch("model.factory.ChatOpenAI") as chat_openai:
            ChatModelFactory(settings=settings).generator()

        kwargs = chat_openai.call_args.kwargs
        self.assertEqual(kwargs["request_timeout"], 12.5)
        self.assertEqual(kwargs["max_retries"], 4)
        self.assertNotIn("http_client", kwargs)
        self.assertNotIn("http_async_client", kwargs)

    def test_openai_factory_builds_ca_verified_http_clients(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = Path(temp_dir) / "private-ca.pem"
            bundle.write_text("test certificate placeholder", encoding="utf-8")
            settings = Settings.model_validate(
                {
                    "model_provider": "openai",
                    "openai_api_key": "dummy",
                    "model_request_timeout_seconds": 20,
                    "model_ca_bundle": bundle,
                }
            )

            with (
                patch("model.factory.ChatOpenAI") as chat_openai,
                patch("model.factory.httpx.Client") as sync_client,
                patch("model.factory.httpx.AsyncClient") as async_client,
                patch("model.factory.ssl.create_default_context") as create_context,
            ):
                ChatModelFactory(settings=settings).generator()

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
            settings = Settings.model_validate(
                {
                    "model_provider": "anthropic",
                    "anthropic_auth_token": "dummy",
                    "model_request_timeout_seconds": 18,
                    "model_ca_bundle": bundle,
                }
            )

            with patch("model.factory.AnthropicCompatibleChatModel") as anthropic_model:
                ChatModelFactory(settings=settings).generator()

        kwargs = anthropic_model.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 18.0)
        self.assertEqual(kwargs["verify"], str(bundle.resolve()))

    def test_factory_does_not_replace_global_tls_context(self) -> None:
        self.assertIs(ssl._create_default_https_context, ssl.create_default_context)


if __name__ == "__main__":
    unittest.main()
