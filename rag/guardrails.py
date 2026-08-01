from __future__ import annotations

import re
from dataclasses import dataclass


def normalize_query(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


@dataclass(frozen=True)
class GuardrailPolicy:
    """Versioned deterministic baseline for domain-out-of-scope detection."""

    version: str
    unsupported_terms: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.version.strip() or not self.unsupported_terms:
            raise ValueError("guardrail policy requires version and terms")

    def is_out_of_scope(self, query: str) -> bool:
        normalized = normalize_query(query)
        return any(term in normalized for term in self.unsupported_terms)


DEFAULT_GUARDRAIL_POLICY = GuardrailPolicy(
    version="out-of-scope-v1",
    unsupported_terms=(
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
    ),
)


def is_out_of_scope_query(
    query: str, policy: GuardrailPolicy = DEFAULT_GUARDRAIL_POLICY
) -> bool:
    return policy.is_out_of_scope(query)


def low_confidence_response() -> str:
    return "知识库未提供足够依据，建议转人工客服进一步确认。"
