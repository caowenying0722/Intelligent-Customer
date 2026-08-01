from __future__ import annotations

import os
import re
from pathlib import Path

MARKDOWN_LINK_RE = re.compile(r"^\[(?P<label>[^\]]+)\]\((?P<url>[^)]+)\)$")


def clean_env_value(value: str) -> str:
    cleaned = value.strip().strip('"').strip("'")
    match = MARKDOWN_LINK_RE.match(cleaned)
    if match:
        return match.group("url").strip()
    return cleaned


def load_env_file(env_path: str | Path, override: bool = False) -> None:
    path = Path(env_path)
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = clean_env_value(value)
