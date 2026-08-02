from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.app.infrastructure.checkpoints import (
    PostgresCheckpointRuntime,
    build_checkpoint_runtime,
    normalize_psycopg_dsn,
)
from src.app.main import create_app


class FakeConnection:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.executed: list[str] = []

    def execute(self, statement: str) -> FakeConnection:
        if self.fail:
            raise OSError("database unavailable")
        self.executed.append(statement)
        return self

    def fetchone(self) -> tuple[int]:
        return (1,)


class FakePool:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.open_calls: list[tuple[bool, float]] = []
        self.closed = False
        self.connection_value = FakeConnection()

    def open(self, *, wait: bool, timeout: float) -> None:
        self.open_calls.append((wait, timeout))

    @contextmanager
    def connection(self, *, timeout: float):
        assert timeout > 0
        yield self.connection_value

    def close(self) -> None:
        self.closed = True


class FakeSaver:
    def __init__(self, pool: FakePool) -> None:
        self.pool = pool
        self.setup_calls = 0

    def setup(self) -> None:
        self.setup_calls += 1


def _runtime() -> PostgresCheckpointRuntime:
    return PostgresCheckpointRuntime(
        "postgresql+psycopg://app:secret@db:5432/app?sslmode=disable",
        pool_size=3,
        connect_timeout=2,
        pool_factory=FakePool,
        saver_factory=FakeSaver,
        row_factory=object(),
    )


def test_checkpoint_runtime_normalizes_dsn_and_owns_pool_lifecycle() -> None:
    runtime = _runtime()

    assert runtime.database_url == (
        "postgresql://app:secret@db:5432/app?sslmode=disable"
    )
    assert runtime.pool.kwargs["open"] is False
    assert runtime.pool.kwargs["max_size"] == 3
    assert runtime.check_ready() is False

    runtime.start()
    runtime.start()

    assert runtime.started is True
    assert runtime.pool.open_calls == [(True, 2)]
    assert runtime.checkpointer.setup_calls == 1
    assert runtime.check_ready() is True

    runtime.close()
    runtime.close()

    assert runtime.started is False
    assert runtime.pool.closed is True


def test_checkpoint_readiness_fails_closed() -> None:
    runtime = _runtime()
    runtime.start()
    runtime.pool.connection_value.fail = True

    assert runtime.check_ready() is False


def test_checkpoint_runtime_rejects_non_postgres_and_skips_sqlite() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        normalize_psycopg_dsn("sqlite:///app.db")
    assert build_checkpoint_runtime("sqlite:///app.db") is None
    assert build_checkpoint_runtime(None) is None


def test_application_lifespan_starts_and_closes_resources() -> None:
    events: list[str] = []

    class Resource:
        def start(self) -> None:
            events.append("start")

        def close(self) -> None:
            events.append("close")

    with TestClient(create_app(lifecycle_resources=(Resource(),))) as client:
        assert events == ["start"]
        assert client.get("/health/live").status_code == 200

    assert events == ["start", "close"]
