from __future__ import annotations

import unittest

from evaluation.ragas_runner import (
    _build_new_metrics,
    _new_ragas_row,
    _normalize_requested_metric_names,
    parse_ragas_metric_spec,
    resolve_ragas_eval_mode,
    should_include_contexts,
)


class RagasMetricSpecTest(unittest.TestCase):
    def test_parse_factual_correctness_mode(self) -> None:
        spec = parse_ragas_metric_spec("factual_correctness(mode=f1)")

        self.assertEqual(spec.name, "factual_correctness")
        self.assertEqual(spec.params, {"mode": "f1"})
        self.assertEqual(spec.output_name, "factual_correctness(mode=f1)")

    def test_normalize_factual_correctness_alias(self) -> None:
        spec = parse_ragas_metric_spec("factual_correctness(mode=f1)")

        normalized = _normalize_requested_metric_names({"factual_correctness": 0.91}, [spec])

        self.assertEqual(normalized["factual_correctness(mode=f1)"], 0.91)

    def test_normalize_answer_relevancy_alias(self) -> None:
        spec = parse_ragas_metric_spec("answer_relevancy")

        normalized = _normalize_requested_metric_names({"response_relevancy": 0.73}, [spec])

        self.assertEqual(normalized["answer_relevancy"], 0.73)

    def test_build_new_metrics_sets_factual_correctness_f1_when_ragas_installed(self) -> None:
        try:
            import ragas  # noqa: F401
        except ImportError:
            self.skipTest("ragas is not installed")

        metrics = _build_new_metrics(["answer_relevancy", "factual_correctness(mode=f1)"])

        self.assertEqual([type(metric).__name__ for metric in metrics], ["AnswerRelevancy", "FactualCorrectness"])
        self.assertEqual(getattr(metrics[1], "mode", None), "f1")

    def test_minimal_data_mode_omits_contexts_for_target_metrics(self) -> None:
        metric_names = ["answer_relevancy", "factual_correctness(mode=f1)"]

        self.assertFalse(should_include_contexts(metric_names, "minimal"))

        row = {
            "question": "q",
            "answer": "a",
            "reference_answer": "r",
            "contexts": ["secret context"],
        }
        payload = _new_ragas_row(row, include_contexts=False)

        self.assertEqual(set(payload), {"user_input", "response", "reference"})

    def test_minimal_data_mode_includes_contexts_for_context_metrics(self) -> None:
        self.assertTrue(should_include_contexts(["context_recall"], "minimal"))

    def test_default_eval_mode_is_per_sample(self) -> None:
        self.assertEqual(resolve_ragas_eval_mode(None), "per_sample")

    def test_invalid_eval_mode_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            resolve_ragas_eval_mode("whole_dataset")


if __name__ == "__main__":
    unittest.main()
