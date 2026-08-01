import pytest
from langchain_core.documents import Document

from rag.rrf import reciprocal_rank_fusion, reciprocal_rank_fusion_scored
from rag.retrieval_types import (
    RetrievalResult,
    build_chroma_scope_filter,
    filter_documents_by_scope,
)
from rag.simple_bm25 import RRFHybridRetriever


def test_rrf_deduplicates_and_matches_hand_calculation() -> None:
    result = reciprocal_rank_fusion(
        [["a", "b", "c"], ["b", "a", "d"]], k=1
    )

    # b and a both receive 1/2 + 1/3; the stable first-seen order wins.
    assert result == ["a", "b", "c", "d"]
    assert reciprocal_rank_fusion_scored([["a"], ["a"]], k=1) == [("a", 1.0)]


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
                "index_version": "idx-1",
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


def test_scope_filter_fails_closed_for_tenant_and_index_mismatch() -> None:
    documents = [
        Document(
            page_content="allowed",
            metadata={"tenant_id": "tenant-a", "index_version": "idx-1"},
        ),
        Document(
            page_content="other tenant",
            metadata={"tenant_id": "tenant-b", "index_version": "idx-1"},
        ),
        Document(
            page_content="old index",
            metadata={"tenant_id": "tenant-a", "index_version": "idx-0"},
        ),
        Document(page_content="unscoped", metadata={}),
    ]
    filtered = filter_documents_by_scope(
        documents, tenant_id="tenant-a", index_version="idx-1"
    )
    assert [document.page_content for document in filtered] == ["allowed"]


def test_chroma_scope_filter_rejects_partial_index_scope() -> None:
    assert build_chroma_scope_filter(tenant_id="tenant-a") == {
        "tenant_id": "tenant-a"
    }
    assert build_chroma_scope_filter(
        tenant_id="tenant-a", index_version="idx-1"
    ) == {
        "$and": [{"tenant_id": "tenant-a"}, {"index_version": "idx-1"}]
    }
    with pytest.raises(ValueError, match="tenant_id"):
        build_chroma_scope_filter(index_version="idx-1")


def test_rrf_adapter_exposes_versioned_results() -> None:
    class FakeRetriever:
        def invoke(self, query: str):
            return [
                Document(
                    page_content="answer",
                    metadata={
                        "tenant_id": "tenant-a",
                        "index_version": "idx-2",
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
    assert results[0].fused_score is not None
