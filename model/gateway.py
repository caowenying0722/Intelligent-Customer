"""Provider-neutral model gateway with bounded timeout and retry semantics."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable, Mapping
from typing import Any
import threading
import time
from collections import deque


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
        max_concurrency: int = 8,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
        rate_limit_per_second: int | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if max_concurrency < 1 or failure_threshold < 1 or cooldown_seconds <= 0:
            raise ValueError("gateway limits must be positive")
        if rate_limit_per_second is not None and rate_limit_per_second < 1:
            raise ValueError("rate_limit_per_second must be positive")
        self.providers = dict(providers)
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._semaphore = threading.BoundedSemaphore(max_concurrency)
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.rate_limit_per_second = rate_limit_per_second
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._calls = 0
        self._failures = 0
        self._provider_calls: dict[str, int] = {}
        self._provider_failures: dict[str, int] = {}
        self._rate_calls: deque[float] = deque()

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"calls": self._calls, "failures": self._failures}

    def audit_snapshot(self) -> dict[str, object]:
        """Return aggregate counters only; never include request/response data."""
        with self._lock:
            return {
                "calls": self._calls,
                "failures": self._failures,
                "provider_calls": dict(self._provider_calls),
                "provider_failures": dict(self._provider_failures),
            }

    def _check_breaker(self) -> None:
        with self._lock:
            if self._opened_at is None:
                return
            if time.monotonic() - self._opened_at < self.cooldown_seconds:
                raise ModelGatewayError("model gateway circuit is open")
            self._opened_at = None
            self._consecutive_failures = 0

    def _check_rate_limit(self) -> None:
        if self.rate_limit_per_second is None:
            return
        now = time.monotonic()
        with self._lock:
            while self._rate_calls and now - self._rate_calls[0] >= 1.0:
                self._rate_calls.popleft()
            if len(self._rate_calls) >= self.rate_limit_per_second:
                raise ModelGatewayError("model gateway rate limit reached")
            self._rate_calls.append(now)

    def _record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0

    def _record_failure(self, provider: str | None = None) -> None:
        with self._lock:
            self._failures += 1
            if provider is not None:
                self._provider_failures[provider] = self._provider_failures.get(provider, 0) + 1
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.failure_threshold:
                self._opened_at = time.monotonic()

    def invoke(self, *, provider: str, request: Any) -> Any:
        operation = self.providers.get(provider)
        if operation is None:
            raise ModelGatewayError(f"model provider is not configured: {provider}")
        self._check_breaker()
        self._check_rate_limit()
        acquired = self._semaphore.acquire(timeout=self.timeout_seconds)
        if not acquired:
            raise ModelGatewayError("model gateway concurrency limit reached")
        with self._lock:
            self._calls += 1
            self._provider_calls[provider] = self._provider_calls.get(provider, 0) + 1
        try:
            for attempt in range(1, self.max_retries + 2):
                executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="model-call")
                future = executor.submit(operation, request)
                try:
                    result = future.result(timeout=self.timeout_seconds)
                    self._record_success()
                    return result
                except TimeoutError as exc:
                    future.cancel()
                    if attempt > self.max_retries:
                        self._record_failure(provider)
                        raise ModelGatewayError("model request exceeded configured timeout") from exc
                except PermanentModelError as exc:
                    self._record_failure(provider)
                    raise ModelGatewayError("model provider rejected the request") from exc
                except RetryableModelError as exc:
                    if attempt > self.max_retries:
                        self._record_failure(provider)
                        raise ModelGatewayError("model provider retries exhausted") from exc
                except Exception as exc:
                    self._record_failure(provider)
                    raise ModelGatewayError("model provider call failed") from exc
                finally:
                    executor.shutdown(wait=False, cancel_futures=True)
            self._record_failure(provider)
            raise ModelGatewayError("model provider retries exhausted")
        finally:
            self._semaphore.release()

    def invoke_routed(
        self,
        *,
        route: str,
        request: Any,
        routes: Mapping[str, str],
        fallbacks: Mapping[str, list[str]] | None = None,
    ) -> Any:
        """Resolve a stable model alias and try its bounded fallback chain."""
        provider = routes.get(route)
        if provider is None:
            raise ModelGatewayError(f"model route is not configured: {route}")
        candidates = [provider, *(fallbacks or {}).get(route, [])]
        last_error: ModelGatewayError | None = None
        for candidate in dict.fromkeys(candidates):
            try:
                return self.invoke(provider=candidate, request=request)
            except ModelGatewayError as exc:
                last_error = exc
        raise ModelGatewayError(f"all providers failed for model route: {route}") from last_error
