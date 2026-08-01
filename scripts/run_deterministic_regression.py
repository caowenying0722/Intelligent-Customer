"""Run the frozen retrieval regression without model or network calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langchain_core.documents import Document

from evaluation.frozen_regression import load_frozen_regression
from evaluation.regression_report import (
    build_retrieval_regression_summary,
    repository_snapshot,
)
from rag.simple_bm25 import SimpleBM25Retriever
from rag.tokenization import cjk_bm25_tokenizer
from utils.path_tool import get_abs_path


def _load_text_documents() -> list[Document]:
    data_dir = Path(get_abs_path("data"))
    documents: list[Document] = []
    for path in sorted(data_dir.glob("*.txt")):
        documents.append(
            Document(
                page_content=path.read_text(encoding="utf-8"),
                metadata={"source": path.name},
            )
        )
    if not documents:
        raise RuntimeError("no deterministic retrieval source documents found")
    return documents


def run(dataset_path: str, output_path: str, limit: int | None = None) -> Path:
    samples = load_frozen_regression(dataset_path)
    if limit is not None:
        samples = samples[:limit]
    retriever = SimpleBM25Retriever(
        _load_text_documents(), preprocess_func=cjk_bm25_tokenizer, k=10
    )
    rows = []
    for sample in samples:
        docs = retriever.invoke(sample.question)
        rows.append(
            {
                "id": sample.sample_id,
                "question": sample.question,
                "retrieved_sources": [
                    str(doc.metadata.get("source", "")) for doc in docs
                ],
            }
        )
    regression_summary = build_retrieval_regression_summary(rows, dataset_path)
    summary = {
        "retrieval_regression": regression_summary,
        "repository": repository_snapshot(),
        "retriever": {"name": "simple_bm25", "k": 10, "model_calls": 0},
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="data/evaluation/retrieval_regression_v1.json")
    parser.add_argument("--output", default="output/evaluation/deterministic-summary.json")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    print(run(args.dataset, args.output, args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
