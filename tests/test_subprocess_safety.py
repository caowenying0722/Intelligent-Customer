from __future__ import annotations

import ast
import unittest
from pathlib import Path

from scripts import run_quality_pipeline, run_ragas_ablation

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_SCRIPTS = (
    PROJECT_ROOT / "scripts" / "run_quality_pipeline.py",
    PROJECT_ROOT / "scripts" / "run_ragas_ablation.py",
)


class SubprocessSafetyTest(unittest.TestCase):
    def test_pipeline_subprocesses_have_check_and_timeout(self) -> None:
        for path in PIPELINE_SCRIPTS:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            calls = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"
                and node.func.attr == "run"
            ]
            self.assertTrue(calls, msg=f"No subprocess.run call found in {path}")
            for call in calls:
                keyword_names = {keyword.arg for keyword in call.keywords}
                with self.subTest(path=path, line=call.lineno):
                    self.assertIn("check", keyword_names)
                    self.assertIn("timeout", keyword_names)

        self.assertLessEqual(run_quality_pipeline.SUBPROCESS_TIMEOUT_SECONDS, 1800)
        self.assertLessEqual(run_ragas_ablation.SUBPROCESS_TIMEOUT_SECONDS, 1800)


if __name__ == "__main__":
    unittest.main()
