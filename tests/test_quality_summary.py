from __future__ import annotations

import unittest
from pathlib import Path

from scripts.summarize_quality_report import DEFAULT_FOCUS_METRICS, build_markdown, metric_rows


class QualitySummaryTest(unittest.TestCase):
    def test_default_focus_prioritizes_official_ragas_metrics(self) -> None:
        self.assertEqual(DEFAULT_FOCUS_METRICS[:2], ["answer_relevancy", "factual_correctness(mode=f1)"])

    def test_metric_rows_includes_official_metrics_first(self) -> None:
        comparison = {
            "metrics": {
                "answer_keyword_accuracy": {
                    "baseline": 0.7,
                    "improved": 0.8,
                    "percentage_point_delta": 10.0,
                    "relative_percent_delta": 14.29,
                },
                "answer_relevancy": {
                    "baseline": 0.6,
                    "improved": 0.7,
                    "percentage_point_delta": 10.0,
                    "relative_percent_delta": 16.67,
                },
                "factual_correctness(mode=f1)": {
                    "baseline": 0.5,
                    "improved": 0.55,
                    "percentage_point_delta": 5.0,
                    "relative_percent_delta": 10.0,
                },
            }
        }

        rows = metric_rows(comparison, DEFAULT_FOCUS_METRICS)

        self.assertEqual([row[0] for row in rows[:2]], ["answer_relevancy", "factual_correctness(mode=f1)"])

    def test_markdown_marks_missing_official_metrics(self) -> None:
        comparison = {
            "ragas_enabled": True,
            "sample_count": 1,
            "improved_ragas_error": "RAGAS returned no finite metric values.",
            "improved_judge_llm": {
                "provider": "anthropic-compatible",
                "chat_model_name": "deepseek-v4-flash",
                "present_keys": ["ANTHROPIC_AUTH_TOKEN"],
            },
            "metrics": {
                "answer_keyword_accuracy": {
                    "baseline": 0.7,
                    "improved": 0.8,
                    "percentage_point_delta": 10.0,
                    "relative_percent_delta": 14.29,
                }
            },
        }

        markdown = build_markdown(Path("comparison.json"), comparison, metric_rows(comparison, DEFAULT_FOCUS_METRICS))

        self.assertIn("Official RAGAS metrics: not available", markdown)
        self.assertIn("Judge LLM: anthropic-compatible / deepseek-v4-flash", markdown)
        self.assertIn("Judge key present: ANTHROPIC_AUTH_TOKEN", markdown)
        self.assertIn("RAGAS was enabled", markdown)
        self.assertIn("Latest RAGAS error: RAGAS returned no finite metric values.", markdown)

    def test_markdown_handles_no_positive_deltas(self) -> None:
        comparison = {
            "ragas_enabled": False,
            "sample_count": 1,
            "metrics": {
                "answer_keyword_accuracy": {
                    "baseline": 1.0,
                    "improved": 1.0,
                    "percentage_point_delta": 0.0,
                    "relative_percent_delta": 0.0,
                }
            },
        }

        markdown = build_markdown(Path("comparison.json"), comparison, metric_rows(comparison, DEFAULT_FOCUS_METRICS))

        self.assertIn("No positive metric deltas", markdown)


if __name__ == "__main__":
    unittest.main()
