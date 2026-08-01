from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from importlib import metadata
from pathlib import Path

from scripts.check_environment import (
    PROJECT_ROOT,
    RequirementPin,
    collect_installed_versions,
    ensure_consistent_pins,
    parse_pinned_requirements,
    validate_environment,
)


class EnvironmentCheckTest(unittest.TestCase):
    def test_quality_script_imports_do_not_mutate_python_path(self) -> None:
        original_path = list(sys.path)

        for module_name in (
            "scripts.compare_rag_ablation",
            "scripts.evaluate_rag",
            "scripts.preflight_ragas",
            "scripts.summarize_quality_report",
            "scripts.validate_quality_goal",
        ):
            importlib.import_module(module_name)

        self.assertEqual(sys.path, original_path)

    def test_agent_middleware_imports_with_locked_langchain(self) -> None:
        importlib.import_module("agent.tools.middleware")

    def test_repository_declares_supported_python_and_pinned_dev_tools(self) -> None:
        self.assertEqual(
            (PROJECT_ROOT / ".python-version").read_text(encoding="utf-8").strip(),
            "3.10.20",
        )

        pins = ensure_consistent_pins(
            parse_pinned_requirements(PROJECT_ROOT / "requirements-dev.txt")
        )

        self.assertEqual(len(pins), 26)
        self.assertEqual(pins["fastapi"].version, "0.141.1")
        self.assertEqual(pins["langchain"].version, "1.3.9")
        self.assertEqual(pins["langchain-core"].version, "1.4.7")
        self.assertEqual(pins["langchain-community"].version, "0.3.31")
        self.assertEqual(pins["langchain-chroma"].version, "1.1.0")
        self.assertEqual(pins["chromadb"].version, "1.3.7")
        self.assertEqual(pins["langchain-text-splitters"].version, "1.1.2")
        self.assertEqual(pins["langgraph"].version, "1.2.10")
        self.assertEqual(pins["streamlit"].version, "1.54.0")
        self.assertEqual(pins["pillow"].version, "12.3.0")
        self.assertEqual(pins["pypdf"].version, "6.14.2")
        self.assertEqual(pins["langchain-openai"].version, "1.1.14")
        self.assertEqual(pins["langchain-huggingface"].version, "1.2.2")
        self.assertEqual(pins["sentence-transformers"].version, "5.2.0")
        self.assertEqual(pins["transformers"].version, "5.14.1")
        self.assertEqual(pins["pytest"].version, "9.1.1")
        self.assertEqual(pins["ruff"].version, "0.16.1")
        self.assertEqual(pins["mypy"].version, "2.3.0")
        self.assertEqual(pins["coverage"].version, "7.15.2")
        self.assertEqual(pins["pip-audit"].version, "2.10.1")

    def test_parses_nested_exact_pins(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "runtime.txt").write_text("Example_Pkg==1.2.3\n", encoding="utf-8")
            (root / "dev.txt").write_text(
                "-r runtime.txt\nruff==0.16.1\n", encoding="utf-8"
            )

            pins = ensure_consistent_pins(parse_pinned_requirements(root / "dev.txt"))

        self.assertEqual(set(pins), {"example-pkg", "ruff"})
        self.assertEqual(pins["example-pkg"].version, "1.2.3")

    def test_rejects_unpinned_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "requirements.txt"
            path.write_text("ruff>=0.16\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "exact == pin"):
                parse_pinned_requirements(path)

    def test_rejects_conflicting_nested_pins(self) -> None:
        first = RequirementPin("demo", "1.0", Path("a.txt"), 1)
        second = RequirementPin("Demo", "2.0", Path("b.txt"), 1)

        with self.assertRaisesRegex(ValueError, "Conflicting pins"):
            ensure_consistent_pins([first, second])

    def test_reports_python_missing_and_version_mismatches(self) -> None:
        pins = {
            "alpha": RequirementPin("alpha", "1.0", Path("requirements.txt"), 1),
            "beta": RequirementPin("beta", "2.0", Path("requirements.txt"), 2),
        }

        errors = validate_environment(
            pins,
            {"alpha": "0.9", "beta": None},
            python_version=(3, 11),
        )

        self.assertEqual(len(errors), 3)
        self.assertTrue(any("Unsupported Python 3.11" in error for error in errors))
        self.assertTrue(any("Version mismatch for alpha" in error for error in errors))
        self.assertTrue(any("Missing distribution: beta" in error for error in errors))

    def test_collect_installed_versions_marks_missing_distribution(self) -> None:
        pins = {
            "alpha": RequirementPin("alpha", "1.0", Path("requirements.txt"), 1),
            "beta": RequirementPin("beta", "2.0", Path("requirements.txt"), 2),
        }

        def version_reader(name: str) -> str:
            if name == "beta":
                raise metadata.PackageNotFoundError(name)
            return "1.0"

        installed = collect_installed_versions(pins, version_reader=version_reader)

        self.assertEqual(installed, {"alpha": "1.0", "beta": None})


if __name__ == "__main__":
    unittest.main()
