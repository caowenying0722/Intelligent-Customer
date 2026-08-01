from langchain_core.documents import Document

from evaluation.local_metrics import citation_support, citation_validity


def _documents() -> list[Document]:
    return [
        Document(page_content="滤网需要每周清洁"),
        Document(page_content="水箱需要及时补水"),
    ]


def test_citation_validity_and_support_are_separate() -> None:
    supported = "滤网需要每周清洁。【资料1】"
    wrong_evidence = "滤网需要每周清洁。【资料2】"

    assert citation_validity(supported, _documents()) == 1.0
    assert citation_support(supported, _documents()) == 1.0
    assert citation_validity(wrong_evidence, _documents()) == 1.0
    assert citation_support(wrong_evidence, _documents()) == 0.0


def test_out_of_range_citation_is_invalid_and_unsupported() -> None:
    answer = "滤网需要每周清洁。【资料3】"

    assert citation_validity(answer, _documents()) == 0.0
    assert citation_support(answer, _documents()) == 0.0
