import time

from langchain_core.documents import Document

from rag.reranker import CrossEncoderRerankerAdapter


def _docs() -> list[Document]:
    return [
        Document(page_content="first", metadata={"source": "a.pdf"}),
        Document(page_content="second", metadata={"source": "b.pdf"}),
    ]


def test_cross_encoder_adapter_bounds_candidates_and_sorts_scores() -> None:
    seen: list[int] = []

    def scorer(query: str, docs: list[Document]) -> list[float]:
        seen.append(len(docs))
        return [0.1, 0.9]

    result = CrossEncoderRerankerAdapter(
        scorer, max_candidates=2, timeout_seconds=1
    ).rerank("q", _docs(), top_k=1)
    assert seen == [2]
    assert [doc.page_content for doc in result] == ["second"]


def test_cross_encoder_timeout_has_explicit_deterministic_fallback() -> None:
    def slow_scorer(query: str, docs: list[Document]) -> list[float]:
        time.sleep(0.05)
        return [1.0] * len(docs)

    result = CrossEncoderRerankerAdapter(slow_scorer, timeout_seconds=0.001).rerank(
        "first", _docs(), top_k=1
    )
    assert len(result) == 1
    assert result[0].metadata["rerank_degraded"] is True


def test_cross_encoder_adapter_rejects_invalid_top_k() -> None:
    adapter = CrossEncoderRerankerAdapter(max_candidates=1)
    try:
        adapter.rerank("q", _docs(), top_k=0)
    except ValueError as exc:
        assert "top_k" in str(exc)
    else:
        raise AssertionError("invalid top_k was accepted")
