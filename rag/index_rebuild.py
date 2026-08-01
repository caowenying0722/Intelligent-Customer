"""Bounded application orchestration for blue/green index rebuilds."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class AliasBackend(Protocol):
    def switch_active_alias(self, *, alias_name: str, target_collection: str) -> None: ...

    def rollback_active_alias(self, *, alias_name: str, previous_collection: str) -> None: ...


class IndexRebuildError(RuntimeError):
    """A candidate index could not be validated or activated."""


class BlueGreenIndexCoordinator:
    def __init__(self, backend: AliasBackend, *, alias_name: str = "active") -> None:
        if not alias_name.strip():
            raise ValueError("alias_name must not be empty")
        self.backend = backend
        self.alias_name = alias_name

    def rebuild(
        self,
        *,
        previous_collection: str,
        build_candidate: Callable[[], str],
        validate_candidate: Callable[[str], bool],
    ) -> str:
        """Build and validate once, then atomically switch the alias.

        A failed validation never touches the active alias. If activation raises,
        the known-good previous collection is restored before the error escapes.
        """
        if not previous_collection.strip():
            raise ValueError("previous_collection must not be empty")
        try:
            candidate = build_candidate()
        except Exception as exc:
            raise IndexRebuildError("candidate index build failed") from exc
        if not isinstance(candidate, str) or not candidate.strip():
            raise IndexRebuildError("candidate builder returned an invalid collection")
        try:
            valid = validate_candidate(candidate)
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
                raise IndexRebuildError("index activation and rollback failed") from rollback_exc
            raise IndexRebuildError("candidate index activation failed") from exc
        return candidate
