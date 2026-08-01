from __future__ import annotations

import unittest

from scripts.validate_quality_goal import (
    OFFICIAL_RAGAS_METRICS,
    PROXY_FALLBACK_METRICS,
    metric_delta,
    metric_has_positive_delta,
    metric_present,
)


class QualityGoalValidatorTest(unittest.TestCase):
    def test_metric_delta_reads_percentage_points(self) -> None:
        comparison = {
            "metrics": {
                "answer_keyword_accuracy": {
                    "percentage_point_delta": 1.73,
                }
            }
        }

        self.assertEqual(metric_delta(comparison, "answer_keyword_accuracy"), 1.73)

    def test_official_metrics_are_required_separately_from_proxy_metrics(self) -> None:
        self.assertEqual(OFFICIAL_RAGAS_METRICS, ["answer_relevancy", "factual_correctness(mode=f1)"])
        self.assertEqual(PROXY_FALLBACK_METRICS, ["answer_relevancy_proxy", "factual_correctness_proxy"])

    def test_metric_present_distinguishes_missing_official_metric(self) -> None:
        comparison = {"metrics": {"answer_relevancy_proxy": {}}}

        self.assertFalse(metric_present(comparison, "answer_relevancy"))
        self.assertTrue(metric_present(comparison, "answer_relevancy_proxy"))

    def test_official_metric_requires_positive_delta(self) -> None:
        comparison = {
            "metrics": {
                "answer_relevancy": {"percentage_point_delta": 0.0},
                "factual_correctness(mode=f1)": {"percentage_point_delta": 0.42},
            }
        }

        self.assertFalse(metric_has_positive_delta(comparison, "answer_relevancy"))
        self.assertTrue(metric_has_positive_delta(comparison, "factual_correctness(mode=f1)"))


if __name__ == "__main__":
    unittest.main()
