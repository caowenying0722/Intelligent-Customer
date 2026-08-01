from unittest.mock import patch

import pytest

from src.app.observability.tracing import ApiTracer
from utils.settings import Settings


def test_otel_endpoint_defaults_to_no_network_exporter():
    settings = Settings()
    tracer = ApiTracer(
        max_spans=settings.trace_max_spans,
        otlp_endpoint=settings.otel_exporter_endpoint,
        otlp_timeout_seconds=settings.otel_exporter_timeout_seconds,
    )
    try:
        assert settings.otel_exporter_endpoint is None
        assert tracer.remote_exporter is None
    finally:
        tracer.close()


def test_otel_endpoint_rejects_credentials_and_query_data():
    with pytest.raises(ValueError):
        Settings(otel_exporter_endpoint="https://user:pass@example:4317")
    with pytest.raises(ValueError):
        Settings(otel_exporter_endpoint="https://example:4317?token=secret")


def test_production_rejects_plaintext_otel_endpoint():
    with pytest.raises(ValueError, match="HTTPS"):
        Settings(
            application_env="production",
            otel_exporter_endpoint="http://otel-collector:4317",
        )


def test_explicit_otel_exporter_uses_configured_timeout_without_network_call():
    class FakeExporter:
        def export(self, spans):
            return None

        def shutdown(self):
            return None

        def force_flush(self, timeout_millis=30_000):
            return True

    fake_exporter = FakeExporter()
    with patch(
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter",
        return_value=fake_exporter,
    ) as factory:
        tracer = ApiTracer(
            max_spans=8,
            otlp_endpoint="http://127.0.0.1:4317",
            otlp_timeout_seconds=2.5,
        )
        try:
            factory.assert_called_once_with(
                endpoint="http://127.0.0.1:4317",
                insecure=True,
                timeout=2.5,
            )
            assert tracer.remote_exporter is fake_exporter
        finally:
            tracer.close()
