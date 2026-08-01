"""Provider-neutral model gateway with bounded timeout and retry semantics."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable, Mapping
from typing import Any


class ModelGatewayError(RuntimeError):
    """A model call failed after the configured bounded attempts."""


class RetryableModelError(RuntimeError):
    """A provider failure that may be retried."""


class PermanentModelError(RuntimeError):
    """A provider failure that must not be retried."""


class ModelGateway:
    def __init__(
        self,
        providers: Mapping[str, Callable[[Any], Any]],
        *,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        self.providers = dict(providers)
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def invoke(self, *, provider: str, request: Any) -> Any:
        operation = self.providers.get(provider)
        if operation is None:
            raise ModelGatewayError(f"model provider is not configured: {provider}")
        for attempt in range(1, self.max_retries + 2):
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="model-call")
            future = executor.submit(operation, request)
            try:
                return future.result(timeout=self.timeout_seconds)
            except TimeoutError as exc:
                future.cancel()
                if attempt > self.max_retries:
                    raise ModelGatewayError("model request exceeded configured timeout") from exc
            except PermanentModelError as exc:
                raise ModelGatewayError("model provider rejected the request") from exc
            except RetryableModelError as exc:
                if attempt > self.max_retries:
                    raise ModelGatewayError("model provider retries exhausted") from exc
            except Exception as exc:
                raise ModelGatewayError("model provider call failed") from exc
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        raise ModelGatewayError("model provider retries exhausted")
