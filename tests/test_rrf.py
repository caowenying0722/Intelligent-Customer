import pytest
from langchain_core.documents import Document

from rag.rrf import reciprocal_rank_fusion
from rag.retrieval_types import RetrievalResult
from rag.simple_bm25 import RRFHybridRetriever


def test_rrf_deduplicates_and_matches_hand_calculation() -> None:
    result = reciprocal_rank_fusion(
        [["a", "b", "c"], ["b", "a", "d"]], k=1
    )

    # b and a both receive 1/2 + 1/3; the stable first-seen order wins.
    assert result == ["a", "b", "c", "d"]


def test_rrf_supports_empty_rankings_and_limit() -> None:
    assert reciprocal_rank_fusion([[], ["x", "y"]], limit=1) == ["x"]


def test_rrf_uses_custom_key_and_rejects_invalid_parameters() -> None:
    result = reciprocal_rank_fusion(
        [[{"id": "a", "value": 1}], [{"id": "a", "value": 2}]],
        key_fn=lambda item: item["id"],
    )
    assert result == [{"id": "a", "value": 1}]
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"]], k=0)
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"]], limit=-1)


def test_rrf_hybrid_adapter_fuses_two_retrievers() -> None:
    class FakeRetriever:
        def __init__(self, items):
            self.items = items

        def invoke(self, query: str):
            assert query == "q"
            return self.items

    adapter = RRFHybridRetriever(
        FakeRetriever(["a", "b"]), FakeRetriever(["b", "c"]), k=2, fusion_k=1
    )
    assert adapter.invoke("q") == ["b", "a"]


def test_retrieval_result_requires_tenant_and_index_metadata() -> None:
    result = RetrievalResult.from_document(
        Document(
            page_content="answer",
            metadata={
                "tenant_id": "tenant-a",
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "source": "manual.pdf",
            },
        ),
        tenant_id="tenant-a",
        index_version="idx-1",
        final_rank=1,
    )
    assert (result.tenant_id, result.index_version, result.chunk_id) == (
        "tenant-a",
        "idx-1",
        "chunk-1",
    )
    with pytest.raises(ValueError, match="tenant_id"):
        RetrievalResult.from_document(
            Document(page_content="x", metadata={"tenant_id": "tenant-b"}),
            tenant_id="tenant-a",
            index_version="idx-1",
        )


def test_rrf_adapter_exposes_versioned_results() -> None:
    class FakeRetriever:
        def invoke(self, query: str):
            return [
                Document(
                    page_content="answer",
                    metadata={
                        "tenant_id": "tenant-a",
                        "chunk_id": "chunk-1",
                        "document_id": "doc-1",
                    },
                )
            ]

    adapter = RRFHybridRetriever(FakeRetriever(), FakeRetriever(), k=1)
    results = adapter.invoke_results("q", tenant_id="tenant-a", index_version="idx-2")
    assert len(results) == 1
    assert results[0].tenant_id == "tenant-a"
    assert results[0].index_version == "idx-2"
