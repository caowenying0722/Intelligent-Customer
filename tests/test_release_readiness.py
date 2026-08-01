from pathlib import Path


def test_release_readiness_report_is_explicit_about_blockers_and_limits() -> None:
    report = Path("docs/RELEASE_READINESS.md").read_text(encoding="utf-8")

    assert "CVE-2026-45829" in report
    assert "Docker build" in report
    assert "不满足无条件生产发布" in report
    assert "hidden evaluation" in report
