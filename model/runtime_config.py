from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0
MAX_REQUEST_TIMEOUT_SECONDS = 600.0
DEFAULT_MAX_RETRIES = 2
MAX_RETRIES = 5


@dataclass(frozen=True)
class ModelRuntimeConfig:
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    ca_bundle: Path | None = None

    @property
    def requests_verify(self) -> bool | str:
        return str(self.ca_bundle) if self.ca_bundle is not None else True

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        project_root: Path = PROJECT_ROOT,
    ) -> ModelRuntimeConfig:
        source = os.environ if env is None else env
        timeout = _parse_float(
            source.get(
                "MODEL_REQUEST_TIMEOUT_SECONDS", str(DEFAULT_REQUEST_TIMEOUT_SECONDS)
            ),
            name="MODEL_REQUEST_TIMEOUT_SECONDS",
            minimum=0.0,
            maximum=MAX_REQUEST_TIMEOUT_SECONDS,
            minimum_exclusive=True,
        )
        max_retries = _parse_int(
            source.get("MODEL_MAX_RETRIES", str(DEFAULT_MAX_RETRIES)),
            name="MODEL_MAX_RETRIES",
            minimum=0,
            maximum=MAX_RETRIES,
        )
        ca_bundle = _resolve_ca_bundle(source.get("MODEL_CA_BUNDLE", ""), project_root)
        return cls(
            request_timeout_seconds=timeout,
            max_retries=max_retries,
            ca_bundle=ca_bundle,
        )


def _parse_float(
    raw_value: str,
    *,
    name: str,
    minimum: float,
    maximum: float,
    minimum_exclusive: bool = False,
) -> float:
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc

    below_minimum = value <= minimum if minimum_exclusive else value < minimum
    if below_minimum or value > maximum:
        lower_operator = ">" if minimum_exclusive else ">="
        raise ValueError(f"{name} must be {lower_operator} {minimum} and <= {maximum}")
    return value


def _parse_int(raw_value: str, *, name: str, minimum: int, maximum: int) -> int:
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc

    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be >= {minimum} and <= {maximum}")
    return value


def _resolve_ca_bundle(raw_value: str, project_root: Path) -> Path | None:
    if not raw_value.strip():
        return None

    path = Path(raw_value.strip()).expanduser()
    if not path.is_absolute():
        path = project_root / path
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"MODEL_CA_BUNDLE must point to an existing file: {resolved}")
    return resolved
