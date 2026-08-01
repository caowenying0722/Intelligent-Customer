"""Bounded application orchestration for blue/green index rebuilds."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol


class AliasBackend(Protocol):
    def switch_active_alias(
        self, *, alias_name: str, target_collection: str
    ) -> None: ...

    def rollback_active_alias(
        self, *, alias_name: str, previous_collection: str
    ) -> None: ...


class IndexRebuildError(RuntimeError):
    """A candidate index could not be validated or activated."""


class BlueGreenIndexCoordinator:
    def __init__(
        self,
        backend: AliasBackend,
        *,
        alias_name: str = "active",
        timeout_seconds: float = 300.0,
    ) -> None:
        if not alias_name.strip():
            raise ValueError("alias_name must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.backend = backend
        self.alias_name = alias_name
        self.timeout_seconds = timeout_seconds

    def _bounded(self, operation: Callable[[], object], label: str) -> object:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="index-rebuild")
        future = executor.submit(operation)
        try:
            return future.result(timeout=self.timeout_seconds)
        except TimeoutError as exc:
            future.cancel()
            raise IndexRebuildError(f"{label} exceeded configured timeout") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def rebuild(
        self,
        *,
        previous_collection: str,
        build_candidate: Callable[[], str],
        validate_candidate: Callable[[str], bool],
        cleanup_old_collections: Callable[[], object] | None = None,
    ) -> str:
        """Build and validate once, then atomically switch the alias.

        A failed validation never touches the active alias. If activation raises,
        the known-good previous collection is restored before the error escapes.
        """
        if not previous_collection.strip():
            raise ValueError("previous_collection must not be empty")
        try:
            candidate = self._bounded(build_candidate, "candidate build")
        except IndexRebuildError:
            raise
        except Exception as exc:
            raise IndexRebuildError("candidate index build failed") from exc
        if not isinstance(candidate, str) or not candidate.strip():
            raise IndexRebuildError("candidate builder returned an invalid collection")
        try:
            valid = self._bounded(
                lambda: validate_candidate(candidate), "candidate validation"
            )
        except IndexRebuildError:
            raise
        except Exception as exc:
            raise IndexRebuildError("candidate index validation failed") from exc
        if not valid:
            raise IndexRebuildError("candidate index validation rejected")
        try:
            self.backend.switch_active_alias(
                alias_name=self.alias_name, target_collection=candidate
            )
        except Exception as exc:
            try:
                self.backend.rollback_active_alias(
                    alias_name=self.alias_name, previous_collection=previous_collection
                )
            except Exception as rollback_exc:
                raise IndexRebuildError(
                    "index activation and rollback failed"
                ) from rollback_exc
            raise IndexRebuildError("candidate index activation failed") from exc
        if cleanup_old_collections is not None:
            try:
                self._bounded(cleanup_old_collections, "old collection cleanup")
            except IndexRebuildError:
                raise
            except Exception as exc:
                raise IndexRebuildError(
                    "old collection cleanup failed after activation"
                ) from exc
        return candidate
