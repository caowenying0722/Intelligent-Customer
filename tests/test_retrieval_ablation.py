import json
import tempfile
from pathlib import Path

from scripts.run_retrieval_ablation import run


def test_retrieval_ablation_records_five_variants_and_reproducibility() -> None:
    Path("output").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir="output") as directory:
        tmp_path = Path(directory)
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "a.txt").write_text("filter cleaning maintenance", encoding="utf-8")
        (data_dir / "b.txt").write_text(
            "wifi connection troubleshooting", encoding="utf-8"
        )
        dataset = tmp_path / "dataset.json"
        dataset.write_text(
            json.dumps(
                {
                    "dataset_version": "test-v1",
                    "samples": [
                        {
                            "sample_id": "one",
                            "question": "filter cleaning",
                            "expected_sources": ["a.txt"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        output = run(dataset, data_dir, tmp_path / "report.json")
        report = json.loads(output.read_text(encoding="utf-8"))

    assert set(report["variants"]) == {
        "baseline",
        "dense_only",
        "sparse_only",
        "rrf",
        "rrf_rerank",
    }
    assert report["dataset"]["version"] == "test-v1"
    assert len(report["dataset"]["sha256"]) == 64
    assert report["config"]["model_calls"] == 0
    assert report["config"]["fusion"] == {"method": "rrf", "k": 60}
    assert all(item["latency_ms"] >= 0 for item in report["variants"].values())
