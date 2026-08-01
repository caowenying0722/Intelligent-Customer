from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_PYTHON = (3, 10)
PIN_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*)==(?P<version>[^\s;]+)$"
)


@dataclass(frozen=True)
class RequirementPin:
    name: str
    version: str
    source: Path
    line_number: int

    @property
    def canonical_name(self) -> str:
        return canonicalize_name(self.name)


def canonicalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_pinned_requirements(
    path: Path, seen: set[Path] | None = None
) -> list[RequirementPin]:
    resolved_path = path.resolve()
    visited = seen if seen is not None else set()
    if resolved_path in visited:
        raise ValueError(f"Recursive requirements include detected: {resolved_path}")
    visited.add(resolved_path)

    pins: list[RequirementPin] = []
    try:
        lines = resolved_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ValueError(f"Requirements file does not exist: {resolved_path}") from exc

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(("-r ", "--requirement ")):
            include_name = line.split(maxsplit=1)[1]
            pins.extend(
                parse_pinned_requirements(resolved_path.parent / include_name, visited)
            )
            continue

        match = PIN_PATTERN.fullmatch(line)
        if not match:
            raise ValueError(
                f"Dependency must use an exact == pin at {resolved_path}:{line_number}: {line}"
            )
        pins.append(
            RequirementPin(
                name=match.group("name"),
                version=match.group("version"),
                source=resolved_path,
                line_number=line_number,
            )
        )

    visited.remove(resolved_path)
    return pins


def ensure_consistent_pins(pins: Iterable[RequirementPin]) -> dict[str, RequirementPin]:
    unique: dict[str, RequirementPin] = {}
    for pin in pins:
        previous = unique.get(pin.canonical_name)
        if previous and previous.version != pin.version:
            raise ValueError(
                f"Conflicting pins for {pin.name}: {previous.version} at "
                f"{previous.source}:{previous.line_number}, {pin.version} at "
                f"{pin.source}:{pin.line_number}"
            )
        unique[pin.canonical_name] = pin
    return unique


def collect_installed_versions(
    pins: Mapping[str, RequirementPin],
    version_reader: Callable[[str], str] = metadata.version,
) -> dict[str, str | None]:
    installed: dict[str, str | None] = {}
    for canonical_name, pin in pins.items():
        try:
            installed[canonical_name] = version_reader(pin.name)
        except metadata.PackageNotFoundError:
            installed[canonical_name] = None
    return installed


def validate_environment(
    pins: Mapping[str, RequirementPin],
    installed: Mapping[str, str | None],
    python_version: tuple[int, int],
) -> list[str]:
    errors: list[str] = []
    if python_version != SUPPORTED_PYTHON:
        errors.append(
            f"Unsupported Python {python_version[0]}.{python_version[1]}; "
            f"expected {SUPPORTED_PYTHON[0]}.{SUPPORTED_PYTHON[1]}"
        )

    for canonical_name, pin in sorted(pins.items()):
        actual = installed.get(canonical_name)
        if actual is None:
            errors.append(f"Missing distribution: {pin.name}=={pin.version}")
        elif actual != pin.version:
            errors.append(
                f"Version mismatch for {pin.name}: installed {actual}, expected {pin.version}"
            )
    return errors


def run_pip_check(timeout_seconds: int = 120) -> int:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "check"],
            cwd=PROJECT_ROOT,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        print(f"pip check timed out after {timeout_seconds} seconds", file=sys.stderr)
        return 1
    return result.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the supported Python version and exact installed dependency pins."
    )
    parser.add_argument(
        "--requirements",
        type=Path,
        default=PROJECT_ROOT / "requirements.txt",
        help="Pinned requirements file to validate (default: requirements.txt).",
    )
    parser.add_argument(
        "--skip-pip-check", action="store_true", help="Skip `python -m pip check`."
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        pins = ensure_consistent_pins(parse_pinned_requirements(args.requirements))
    except ValueError as exc:
        print(f"Environment check: FAILED\n- {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    installed = collect_installed_versions(pins)
    errors = validate_environment(pins, installed, sys.version_info[:2])
    if not args.skip_pip_check and run_pip_check() != 0:
        errors.append("pip check reported broken dependency relationships")

    if errors:
        print("Environment check: FAILED", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        raise SystemExit(1)

    print(
        f"Environment check: OK (Python {sys.version_info.major}.{sys.version_info.minor}, "
        f"{len(pins)} exact distributions)"
    )


if __name__ == "__main__":
    main()
