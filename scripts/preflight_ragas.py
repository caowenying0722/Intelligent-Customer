from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_DEPS = PROJECT_ROOT / ".local_deps"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_METRICS = ["answer_relevancy", "factual_correctness(mode=f1)"]


def load_project_env() -> None:
    env_path = PROJECT_ROOT / ".env"
    from utils.env_loader import load_env_file

    load_env_file(env_path)


def load_yaml_config(path: Path) -> dict[str, Any]:
    import yaml

    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def import_status(module_name: str) -> dict[str, Any]:
    try:
        module = importlib.import_module(module_name)
        return {
            "ok": True,
            "version": getattr(module, "__version__", "unknown"),
        }
    except Exception as exc:  # noqa: BLE001 - preflight must report arbitrary import failures
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def check_metric_specs(metric_names: list[str]) -> dict[str, Any]:
    from evaluation.ragas_runner import _build_new_metrics, parse_ragas_metric_spec

    parsed = [parse_ragas_metric_spec(name) for name in metric_names]
    try:
        built_metrics = _build_new_metrics(metric_names)
    except Exception as exc:  # noqa: BLE001 - metric plugins may raise provider-specific errors
        return {
            "ok": False,
            "requested": metric_names,
            "parsed": [spec.output_name for spec in parsed],
            "error": f"{type(exc).__name__}: {exc}",
        }

    return {
        "ok": True,
        "requested": metric_names,
        "parsed": [spec.output_name for spec in parsed],
        "resolved_classes": [type(metric).__name__ for metric in built_metrics],
    }


def key_status(rag_config: dict[str, Any]) -> dict[str, Any]:
    from utils.judge_llm import judge_llm_status

    return judge_llm_status(rag_config, PROJECT_ROOT)


def build_report(metric_names: list[str]) -> dict[str, Any]:
    rag_config = load_yaml_config(PROJECT_ROOT / "config" / "rag.yml")
    imports = {
        module_name: import_status(module_name)
        for module_name in ("ragas", "datasets", "langchain_core", "langchain_openai")
    }
    report: dict[str, Any] = {
        "project_root": str(PROJECT_ROOT),
        "local_deps": {
            "path": str(LOCAL_DEPS),
            "exists": LOCAL_DEPS.exists(),
            "active": False,
        },
        "imports": imports,
        "metrics": check_metric_specs(metric_names)
        if imports["ragas"]["ok"]
        else {"ok": False, "error": "ragas import failed"},
        "judge_llm": key_status(rag_config),
    }
    report["ok"] = (
        all(item["ok"] for item in imports.values())
        and report["metrics"]["ok"]
        and report["judge_llm"]["ok"]
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check whether the project can run official RAGAS metrics."
    )
    parser.add_argument(
        "--metrics",
        default=",".join(DEFAULT_METRICS),
        help="Comma-separated metric names to validate.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print machine-readable JSON."
    )
    parser.add_argument(
        "--strict", action="store_true", help="Exit with status 1 when any check fails."
    )
    args = parser.parse_args()

    metric_names = [
        metric.strip() for metric in args.metrics.split(",") if metric.strip()
    ]
    report = build_report(metric_names)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"RAGAS preflight: {'OK' if report['ok'] else 'NOT READY'}")
        print(f"- project_root: {report['project_root']}")
        print(
            f"- legacy local_deps: {report['local_deps']['path']} "
            f"({'exists but inactive' if report['local_deps']['exists'] else 'missing'})"
        )
        for module_name, status in report["imports"].items():
            detail = status.get("version") if status["ok"] else status.get("error")
            print(
                f"- import {module_name}: {'OK' if status['ok'] else 'FAIL'} ({detail})"
            )
        metric_status = report["metrics"]
        print(f"- metrics: {'OK' if metric_status['ok'] else 'FAIL'}")
        if metric_status.get("resolved_classes"):
            print(f"  requested: {', '.join(metric_status['requested'])}")
            print(f"  resolved: {', '.join(metric_status['resolved_classes'])}")
        if metric_status.get("error"):
            print(f"  error: {metric_status['error']}")
        judge = report["judge_llm"]
        print(f"- judge LLM key: {'OK' if judge['ok'] else 'MISSING'}")
        print(f"  provider: {judge['provider']}")
        print(f"  base_url: {judge['chat_base_url']}")
        print(f"  accepted_keys: {', '.join(judge['accepted_keys'])}")
        print(
            f"  present_keys: {', '.join(judge['present_keys']) if judge['present_keys'] else 'none'}"
        )

    if args.strict and not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
