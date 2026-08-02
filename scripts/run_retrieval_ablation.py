"""Run a model-free five-way retrieval ablation over the frozen source set."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langchain_core.documents import Document

from evaluation.hash_embeddings import HashNgramEmbeddings
from evaluation.regression_report import repository_snapshot
from evaluation.retrieval_metrics import evaluate_retrieval
from rag.reranker import LightweightEvidenceReranker
from rag.rrf import reciprocal_rank_fusion
from rag.simple_bm25 import SimpleBM25Retriever, WeightedHybridRetriever
from rag.tokenization import cjk_bm25_tokenizer


class DenseRetriever:
    def __init__(self, documents: list[Document], *, k: int = 10) -> None:
        self.documents = documents
        self.k = k
        self.embeddings = HashNgramEmbeddings()
        self.vectors = self.embeddings.embed_documents(
            [document.page_content for document in documents]
        )

    def invoke(self, query: str) -> list[Document]:
        vector = self.embeddings.embed_query(query)
        scored = [
            (sum(left * right for left, right in zip(vector, candidate)), index, doc)
            for index, (candidate, doc) in enumerate(zip(self.vectors, self.documents))
        ]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [document for _, _, document in scored[: self.k]]


def _load_documents(data_dir: Path) -> list[Document]:
    documents = [
        Document(
            page_content=path.read_text(encoding="utf-8"),
            metadata={"source": path.name},
        )
        for path in sorted(data_dir.glob("*.txt"))
    ]
    if not documents:
        raise ValueError("data directory must contain at least one UTF-8 text file")
    return documents


def run(dataset_path: Path, data_dir: Path, output_path: Path) -> Path:
    raw = dataset_path.read_bytes()
    payload = json.loads(raw)
    samples = payload.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("dataset must contain non-empty samples")
    documents = _load_documents(data_dir)
    dense = DenseRetriever(documents)
    sparse = SimpleBM25Retriever(documents, preprocess_func=cjk_bm25_tokenizer, k=10)
    baseline = WeightedHybridRetriever(dense, sparse, 0.6, 0.4, 10)
    reranker = LightweightEvidenceReranker()
    rankings: dict[str, dict[str, list[str]]] = {
        name: {}
        for name in ("baseline", "dense_only", "sparse_only", "rrf", "rrf_rerank")
    }
    relevant: dict[str, list[str]] = {}
    latency_ms = {name: 0.0 for name in rankings}

    for sample in samples:
        sample_id = str(sample["sample_id"])
        query = str(sample["question"])
        relevant[sample_id] = [str(item) for item in sample["expected_sources"]]
        variants: dict[str, list[Document]] = {}
        for name, retriever in (
            ("baseline", baseline),
            ("dense_only", dense),
            ("sparse_only", sparse),
        ):
            started = time.perf_counter()
            variants[name] = retriever.invoke(query)
            latency_ms[name] += (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        fused = reciprocal_rank_fusion(
            [variants["dense_only"], variants["sparse_only"]], k=60, limit=10
        )
        latency_ms["rrf"] += (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        variants["rrf"] = fused
        variants["rrf_rerank"] = reranker.rerank(query, list(fused), top_k=10)
        latency_ms["rrf_rerank"] += (time.perf_counter() - started) * 1000
        for name, docs in variants.items():
            rankings[name][sample_id] = [str(doc.metadata["source"]) for doc in docs]

    report = {
        "dataset": {
            "version": payload.get("dataset_version"),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "sample_count": len(samples),
        },
        "config": {
            "dense_method": "hash-ngram-v1",
            "sparse_method": "bm25-local-v1",
            "fusion": {"method": "rrf", "k": 60},
            "reranker": "lightweight-evidence-v1",
            "candidate_k": 10,
            "final_k": 10,
            "index_version": "retrieval-regression-v1",
            "model_calls": 0,
        },
        "repository": repository_snapshot(),
        "variants": {
            name: {
                "metrics": evaluate_retrieval(result, relevant),
                "latency_ms": round(latency_ms[name], 3),
            }
            for name, result in rankings.items()
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", default="data/evaluation/retrieval_regression_v1.json"
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output", default="output/evaluation/retrieval-ablation.json")
    args = parser.parse_args()
    print(run(Path(args.dataset), Path(args.data_dir), Path(args.output)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
