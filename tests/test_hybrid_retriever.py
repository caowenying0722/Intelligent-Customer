from langchain_core.documents import Document

from rag.hybrid_retriever import QdrantHybridRetriever, SparseEncoding
from rag.retrieval_types import RetrievalResult


class DenseEncoder:
    def embed_query(self, text: str) -> list[float]:
        assert text == "filter cleaning"
        return [1.0, 0.0]


class SparseEncoder:
    def encode_query(self, text: str) -> SparseEncoding:
        assert text == "filter cleaning"
        return SparseEncoding(indices=[7], values=[1.0])


class Backend:
    def __init__(self) -> None:
        self.call: dict = {}

    def hybrid_search_results(self, dense_vector, **kwargs):
        self.call = {"dense_vector": dense_vector, **kwargs}
        return [
            RetrievalResult(
                chunk_id="chunk-1",
                document_id="doc-1",
                tenant_id="tenant-a",
                document_version="v2",
                index_version="idx-1",
                source="manual",
                fused_score=0.5,
                final_rank=1,
                metadata={"content": "clean the filter", "language": "en"},
            )
        ]


def test_hybrid_retriever_runs_encoders_and_preserves_result_contract() -> None:
    backend = Backend()
    retriever = QdrantHybridRetriever(
        backend,  # type: ignore[arg-type]
        DenseEncoder(),
        SparseEncoder(),
        candidate_k=8,
        final_k=3,
        rrf_k=60,
    )

    documents = retriever.invoke(
        "filter cleaning", tenant_id="tenant-a", index_version="idx-1"
    )

    assert backend.call["tenant_id"] == "tenant-a"
    assert backend.call["index_version"] == "idx-1"
    assert backend.call["sparse_indices"] == [7]
    assert backend.call["prefetch_limit"] == 8
    assert documents == [
        Document(
            page_content="clean the filter",
            metadata={
                "language": "en",
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "tenant_id": "tenant-a",
                "document_version": "v2",
                "index_version": "idx-1",
                "source": "manual",
                "fused_score": 0.5,
                "fused_rank": 1,
                "rerank_applied": False,
            },
        )
    ]


def test_hybrid_retriever_uses_explicit_reranker() -> None:
    class Reranker:
        def rerank(self, query: str, docs: list[Document], top_k: int):
            assert query == "filter cleaning"
            assert top_k == 1
            docs[0].metadata["rerank_applied"] = True
            return docs[:top_k]

    retriever = QdrantHybridRetriever(
        Backend(),  # type: ignore[arg-type]
        DenseEncoder(),
        SparseEncoder(),
        reranker=Reranker(),
        candidate_k=2,
        final_k=1,
    )
    result = retriever.invoke(
        "filter cleaning", tenant_id="tenant-a", index_version="idx-1"
    )
    assert result[0].metadata["rerank_applied"] is True
