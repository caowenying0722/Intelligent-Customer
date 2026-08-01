from pathlib import Path


def test_operations_docs_are_explicit_about_current_limits() -> None:
    incident = Path("docs/operations/incident-runbook.md").read_text(encoding="utf-8")
    backup = Path("docs/operations/backup-restore.md").read_text(encoding="utf-8")

    assert "/health/live" in incident
    assert "Blocker" in incident
    assert "内存会话" in backup
    assert "尚未接入仓库自动化" in backup
