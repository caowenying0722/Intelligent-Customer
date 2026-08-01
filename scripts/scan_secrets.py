from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {
    ".git",
    ".local_deps",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "chroma_db",
    "logs",
    "output",
}

SKIP_FILES = {
    ".env",
}

SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
    ".pyc",
    ".pyo",
}

SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-lf-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bpk-lf-[A-Za-z0-9-]{20,}\b"),
    re.compile(
        r"\bANTHROPIC_AUTH_TOKEN\s*=\s*['\"]?(?!your_|dummy\b)([A-Za-z0-9][A-Za-z0-9_-]{8,})['\"]?"
    ),
    re.compile(
        r"\bANTHROPIC_API_KEY\s*=\s*['\"]?(?!your_|dummy\b)([A-Za-z0-9][A-Za-z0-9_-]{8,})['\"]?"
    ),
    re.compile(
        r"\bOPENAI_API_KEY\s*=\s*['\"]?(?!your_|dummy\b)([A-Za-z0-9][A-Za-z0-9_-]{8,})['\"]?"
    ),
    re.compile(
        r"\bDEEPSEEK_API_KEY\s*=\s*['\"]?(?!your_|dummy\b)([A-Za-z0-9][A-Za-z0-9_-]{8,})['\"]?"
    ),
]


@dataclass(frozen=True)
class Finding:
    path: Path
    line_number: int
    secret: str


def redact(secret: str) -> str:
    if len(secret) <= 10:
        return "***"
    return f"{secret[:6]}...{secret[-4:]}"


def extract_secret(match: re.Match[str]) -> str:
    if match.groups():
        return match.group(1).strip().strip('"').strip("'")
    return match.group(0)


def line_findings(path: Path, line_number: int, line: str) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[str] = set()
    for pattern in SECRET_PATTERNS:
        for match in pattern.finditer(line):
            secret = extract_secret(match)
            if secret in seen:
                continue
            seen.add(secret)
            findings.append(Finding(path=path, line_number=line_number, secret=secret))
    return findings


def should_skip(path: Path, include_private_env: bool) -> bool:
    relative_parts = set(path.relative_to(PROJECT_ROOT).parts)
    if relative_parts & SKIP_DIRS:
        return True
    if path.name in SKIP_FILES and not include_private_env:
        return True
    return path.suffix.lower() in SKIP_SUFFIXES


def iter_files(include_private_env: bool) -> list[Path]:
    files = []
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if should_skip(path, include_private_env=include_private_env):
            continue
        files.append(path)
    return files


def scan(include_private_env: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_files(include_private_env=include_private_env):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            findings.extend(line_findings(path, line_number, line))
    return findings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan project files for accidentally committed API keys."
    )
    parser.add_argument(
        "--include-private-env", action="store_true", help="Also scan local .env files."
    )
    args = parser.parse_args()

    findings = scan(include_private_env=args.include_private_env)
    if not findings:
        print("Secret scan: OK")
        return

    print("Secret scan: FOUND potential secrets")
    for finding in findings:
        relative_path = finding.path.relative_to(PROJECT_ROOT)
        print(f"- {relative_path}:{finding.line_number}: {redact(finding.secret)}")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
