"""Compare explicit baseline/candidate rankings and write a migration artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evaluation.retrieval_comparison import compare_rankings
from evaluation.regression_report import repository_snapshot


def run(input_path: str, output_path: str) -> Path:
    payload: dict[str, Any] = json.loads(Path(input_path).read_text(encoding="utf-8"))
    for field in ("baseline", "candidate", "relevant"):
        if not isinstance(payload.get(field), dict):
            raise ValueError(f"comparison input requires a {field} object")
    report = {
        "comparison": compare_rankings(
            payload["baseline"], payload["candidate"], payload["relevant"]
        ),
        "repository": repository_snapshot(),
        "input": str(Path(input_path).resolve()),
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(run(args.input, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
