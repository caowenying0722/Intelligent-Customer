"""Project-root-relative path helpers."""

from __future__ import annotations

from os import PathLike
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def get_project_root() -> str:
    return str(PROJECT_ROOT)


def get_abs_path(relative_path: str | PathLike[str]) -> str:
    path = Path(relative_path).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path.resolve())


if __name__ == "__main__":
    print(get_abs_path("config/config.txt"))
