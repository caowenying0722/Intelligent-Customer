from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.env_loader import clean_env_value

ENV_PATH = PROJECT_ROOT / ".env"


DEFAULTS = {
    "LLM__PROVIDER": "anthropic",
    "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
    "ANTHROPIC_MODEL": "deepseek-v4-flash",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-flash",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-v4-flash",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-v4-flash",
}


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = clean_env_value(value)
    return values


def write_env(path: Path, values: dict[str, str]) -> None:
    lines = [
        "# Private local environment. Do not commit this file.",
        "",
    ]
    for key in [
        "LLM__PROVIDER",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
    ]:
        value = values.get(key, "")
        if value:
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update the private .env used by RAGAS evaluation.")
    parser.add_argument("--base-url", default=DEFAULTS["ANTHROPIC_BASE_URL"], help="Anthropic-compatible API base URL.")
    parser.add_argument("--model", default=DEFAULTS["ANTHROPIC_MODEL"], help="Judge model name.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing ANTHROPIC_AUTH_TOKEN in .env.")
    parser.add_argument(
        "--from-current-env",
        action="store_true",
        help="Copy ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY from the current shell environment instead of prompting.",
    )
    args = parser.parse_args()

    values = parse_env(ENV_PATH)
    values.update(DEFAULTS)
    values["ANTHROPIC_BASE_URL"] = clean_env_value(args.base_url)
    values["ANTHROPIC_MODEL"] = args.model
    values["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = args.model
    values["ANTHROPIC_DEFAULT_OPUS_MODEL"] = args.model
    values["ANTHROPIC_DEFAULT_SONNET_MODEL"] = args.model

    if args.from_current_env:
        env_token = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
        if env_token and (args.force or not values.get("ANTHROPIC_AUTH_TOKEN")):
            values["ANTHROPIC_AUTH_TOKEN"] = env_token
    elif args.force or not values.get("ANTHROPIC_AUTH_TOKEN"):
        token = getpass.getpass("ANTHROPIC_AUTH_TOKEN: ").strip()
        if token:
            values["ANTHROPIC_AUTH_TOKEN"] = token

    write_env(ENV_PATH, values)
    print(f"Updated {ENV_PATH}")
    print("Run `python scripts/preflight_ragas.py` to verify the setup.")


if __name__ == "__main__":
    main()
