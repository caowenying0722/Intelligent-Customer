from pathlib import Path


def test_release_readiness_report_is_explicit_about_limits() -> None:
    report = Path("docs/RELEASE_READINESS.md").read_text(encoding="utf-8")

    assert "No known vulnerabilities found" in report
    assert "Redis/Celery workers profile" in report
    assert "Docker build" in report
    assert "不满足无条件生产发布" in report
    assert "hidden evaluation" in report
