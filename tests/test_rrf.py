import pytest

from rag.rrf import reciprocal_rank_fusion
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
