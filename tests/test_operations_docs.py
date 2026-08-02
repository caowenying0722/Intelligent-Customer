from pathlib import Path


def test_operations_docs_are_explicit_about_current_limits() -> None:
    incident = Path("docs/operations/incident-runbook.md").read_text(encoding="utf-8")
    backup = Path("docs/operations/backup-restore.md").read_text(encoding="utf-8")
    worker = Path("docs/operations/worker.md").read_text(encoding="utf-8")

    assert "/health/live" in incident
    assert "RAGAS" in incident
    assert "内存会话" in backup
    assert "scripts/postgres_backup.py" in backup
    assert "RPO/RTO" in backup
    assert "acks_late" in worker
    assert "at-least-once" in worker
    assert "JWT_SECRET" in incident
