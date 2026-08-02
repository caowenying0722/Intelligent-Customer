from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.app.infrastructure.postgres_backup import (
    PostgresBackupError,
    PostgresBackupRunner,
    _parse_database_url,
    _safe_database_url,
)


def test_database_url_is_redacted_from_command() -> None:
    parsed = _parse_database_url(
        "postgresql+psycopg://user:super-secret@db:5432/app?sslmode=require"
    )

    safe = _safe_database_url(parsed)

    assert "super-secret" not in safe
    assert safe == "postgresql://user@db:5432/app?sslmode=require"


def test_dump_passes_password_only_in_environment(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs["env"]))
        Path(command[command.index("--file") + 1]).write_bytes(b"PGDUMP")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    archive = PostgresBackupRunner(timeout_seconds=2).dump(
        "postgresql://user:secret@db:5432/app", tmp_path / "backup.dump"
    )

    assert archive.read_bytes() == b"PGDUMP"
    command, environment = calls[0]
    assert "secret" not in " ".join(command)
    assert environment["PGPASSWORD"] == "secret"


def test_restore_requires_explicit_archive_and_clean_flag(
    tmp_path: Path, monkeypatch
) -> None:
    archive = tmp_path / "backup.dump"
    archive.write_bytes(b"dump")
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner = PostgresBackupRunner(timeout_seconds=2)
    runner.restore("postgresql://user:secret@db:5432/app", archive)
    runner.restore("postgresql://user:secret@db:5432/app", archive, destructive=True)

    assert "--clean" not in commands[0]
    assert commands[1][1:3] == ["--exit-on-error", "--no-owner"]
    assert "--clean" in commands[1]


def test_timeout_is_converted_to_safe_error(monkeypatch) -> None:
    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="pg_dump", timeout=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(PostgresBackupError, match="timeout"):
        PostgresBackupRunner(timeout_seconds=1)._run(["pg_dump"], {}, "backup")
