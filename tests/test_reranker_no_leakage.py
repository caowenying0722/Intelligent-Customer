from __future__ import annotations

from langchain_core.documents import Document

from rag.reranker import LightweightEvidenceReranker


def test_source_filename_cannot_change_ranking() -> None:
    reranker = LightweightEvidenceReranker()
    documents = [
        Document(
            page_content="机器人需要定期清洁滤网",
            metadata={"source": "选购指南.txt", "chunk_id": "chunk-1"},
        ),
        Document(
            page_content="机器人需要定期清洁滤网",
            metadata={"source": "维护保养.txt", "chunk_id": "chunk-2"},
        ),
    ]

    result = reranker.rerank("如何清洁滤网？", documents, top_k=2)

    assert [doc.metadata["source"] for doc in result] == [
        "选购指南.txt",
        "维护保养.txt",
    ]
    assert all("source_score" not in doc.metadata["rerank_reason"] for doc in result)


def test_duplicate_identity_does_not_depend_on_source_metadata() -> None:
    reranker = LightweightEvidenceReranker()
    documents = [
        Document(
            page_content="相同内容",
            metadata={"source": "a.txt", "chunk_id": "chunk-1"},
        ),
        Document(
            page_content="相同内容",
            metadata={"source": "b.txt", "chunk_id": "chunk-1"},
        ),
    ]

    result = reranker.rerank("相同内容", documents, top_k=2)

    assert len(result) == 1
