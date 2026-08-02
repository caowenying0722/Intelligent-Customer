"""Bounded, secret-safe PostgreSQL backup and restore operations."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import SplitResult, quote, urlsplit, urlunsplit


class PostgresBackupError(RuntimeError):
    """A backup operation failed without exposing connection credentials."""


@dataclass(frozen=True, slots=True)
class PostgresBackupRunner:
    """Run PostgreSQL client tools with an explicit wall-clock bound.

    Passwords are passed through ``PGPASSWORD`` and never appear in the
    subprocess argument list or error messages. Restore is non-destructive by
    default; dropping existing objects requires an explicit caller flag.
    """

    timeout_seconds: float = 300.0
    pg_dump_bin: str = "pg_dump"
    pg_restore_bin: str = "pg_restore"

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not self.pg_dump_bin.strip() or not self.pg_restore_bin.strip():
            raise ValueError("PostgreSQL client binaries must not be empty")

    def dump(self, database_url: str, destination: str | Path) -> Path:
        """Create a custom-format dump and verify it is non-empty."""

        parsed = _parse_database_url(database_url)
        target = _prepare_destination(destination)
        command = [
            self.pg_dump_bin,
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(target),
            "--dbname",
            _safe_database_url(parsed),
        ]
        try:
            self._run(command, _postgres_env(parsed), "backup")
            if not target.is_file() or target.stat().st_size == 0:
                raise PostgresBackupError("backup command produced an empty file")
        except Exception:
            _remove_partial_file(target)
            raise
        return target

    def verify(self, backup: str | Path) -> int:
        """Validate a custom-format archive and return its listed object count."""

        archive = _require_backup(backup)
        result = self._run(
            [self.pg_restore_bin, "--list", str(archive)],
            os.environ.copy(),
            "backup verification",
        )
        return sum(1 for line in result.stdout.splitlines() if line.strip())

    def restore(
        self,
        database_url: str,
        backup: str | Path,
        *,
        destructive: bool = False,
    ) -> None:
        """Restore an archive into an explicit database.

        ``destructive=True`` adds ``--clean --if-exists`` and must only be used
        for an isolated target or an approved maintenance window.
        """

        parsed = _parse_database_url(database_url)
        archive = _require_backup(backup)
        command = [
            self.pg_restore_bin,
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
        ]
        if destructive:
            command.extend(["--clean", "--if-exists"])
        command.extend(["--dbname", _safe_database_url(parsed), str(archive)])
        self._run(command, _postgres_env(parsed), "restore")

    def _run(
        self,
        command: Sequence[str],
        environment: dict[str, str],
        operation: str,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                list(command),
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=environment,
            )
        except FileNotFoundError as exc:
            raise PostgresBackupError(
                f"{operation} requires the PostgreSQL client tools"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise PostgresBackupError(
                f"{operation} exceeded the configured timeout"
            ) from exc
        except subprocess.CalledProcessError as exc:
            # Do not include stderr: PostgreSQL tools may echo connection URLs.
            raise PostgresBackupError(f"{operation} command failed") from exc


def _parse_database_url(database_url: str) -> SplitResult:
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgresql", "postgresql+psycopg"}:
        raise ValueError("backup operations require a PostgreSQL DATABASE_URL")
    if not parsed.hostname or not parsed.path.strip("/"):
        raise ValueError("DATABASE_URL must include a PostgreSQL host and database")
    return parsed


def _safe_database_url(parsed: SplitResult) -> str:
    """Return a connection URL with credentials removed from the URL."""

    username = parsed.username
    authority = parsed.netloc.rsplit("@", 1)[-1]
    if username:
        authority = f"{quote(username, safe='')}@{authority}"
    scheme = "postgresql"
    return urlunsplit((scheme, authority, parsed.path, parsed.query, ""))


def _postgres_env(parsed: SplitResult) -> dict[str, str]:
    environment = os.environ.copy()
    if parsed.password is None:
        environment.pop("PGPASSWORD", None)
    else:
        environment["PGPASSWORD"] = parsed.password
    return environment


def _prepare_destination(destination: str | Path) -> Path:
    target = Path(destination).expanduser().resolve()
    if target.exists() and target.is_symlink():
        raise ValueError("backup destination must not be a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _require_backup(backup: str | Path) -> Path:
    archive = Path(backup).expanduser().resolve()
    if not archive.is_file() or archive.stat().st_size == 0:
        raise FileNotFoundError(f"backup archive does not exist or is empty: {archive}")
    return archive


def _remove_partial_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
