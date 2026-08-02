"""Lifecycle-managed LangGraph PostgreSQL checkpoint infrastructure."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit


def normalize_psycopg_dsn(database_url: str) -> str:
    """Convert a SQLAlchemy PostgreSQL URL into a psycopg connection string."""

    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgresql", "postgresql+psycopg"}:
        raise ValueError("checkpoint storage requires a PostgreSQL DATABASE_URL")
    return urlunsplit(("postgresql", parsed.netloc, parsed.path, parsed.query, ""))


class PostgresCheckpointRuntime:
    """Own a closed-by-default psycopg pool and its LangGraph saver."""

    def __init__(
        self,
        database_url: str,
        *,
        pool_size: int = 5,
        connect_timeout: float = 10.0,
        pool_factory: Any | None = None,
        saver_factory: Any | None = None,
        row_factory: Any | None = None,
    ) -> None:
        if pool_size < 1:
            raise ValueError("pool_size must be positive")
        if connect_timeout <= 0:
            raise ValueError("connect_timeout must be positive")

        if pool_factory is None or saver_factory is None or row_factory is None:
            try:
                from langgraph.checkpoint.postgres import PostgresSaver
                from psycopg.rows import dict_row
                from psycopg_pool import ConnectionPool
            except ImportError as exc:  # pragma: no cover - clean-install guard.
                raise RuntimeError(
                    "PostgreSQL checkpoint dependencies are not installed"
                ) from exc
            pool_factory = pool_factory or ConnectionPool
            saver_factory = saver_factory or PostgresSaver
            row_factory = row_factory or dict_row

        self.database_url = normalize_psycopg_dsn(database_url)
        self.connect_timeout = connect_timeout
        self.pool = pool_factory(
            conninfo=self.database_url,
            min_size=1,
            max_size=pool_size,
            timeout=connect_timeout,
            open=False,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": row_factory,
            },
        )
        self.checkpointer = saver_factory(self.pool)
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    def start(self) -> None:
        """Open the bounded pool and apply idempotent checkpointer migrations."""

        if self._started:
            return
        self.pool.open(wait=True, timeout=self.connect_timeout)
        try:
            self.checkpointer.setup()
        except Exception:  # noqa: BLE001 - close the pool before re-raising.
            self.pool.close()
            raise
        self._started = True

    def check_ready(self) -> bool:
        if not self._started:
            return False
        try:
            with self.pool.connection(timeout=self.connect_timeout) as connection:
                connection.execute("SELECT 1").fetchone()
        except Exception:  # noqa: BLE001 - readiness must fail closed.
            return False
        return True

    def close(self) -> None:
        if not self._started:
            return
        self.pool.close()
        self._started = False


def build_checkpoint_runtime(
    database_url: str | None,
    *,
    pool_size: int = 5,
    connect_timeout: float = 10.0,
) -> PostgresCheckpointRuntime | None:
    """Create durable checkpoints only for an explicit PostgreSQL database."""

    if not database_url or not database_url.startswith(
        ("postgresql://", "postgresql+psycopg://")
    ):
        return None
    return PostgresCheckpointRuntime(
        database_url,
        pool_size=pool_size,
        connect_timeout=connect_timeout,
    )
