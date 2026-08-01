from __future__ import annotations

import re


def normalize_query(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def is_out_of_scope_query(query: str) -> bool:
    normalized = normalize_query(query)
    unsupported_terms = [
        "手机",
        "空调",
        "氟利昂",
        "退货",
        "退款",
        "七天无理由",
        "医生",
        "发烧",
        "咳嗽",
        "拆机更换",
    ]
    return any(term in normalized for term in unsupported_terms)


def low_confidence_response() -> str:
    return "知识库未提供足够依据，建议转人工客服进一步确认。"
