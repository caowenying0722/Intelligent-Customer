import pytest

from rag.guardrails import (
    DEFAULT_GUARDRAIL_POLICY,
    GuardrailPolicy,
    is_out_of_scope_query,
)


def test_default_guardrail_policy_is_versioned_and_preserves_baseline() -> None:
    assert DEFAULT_GUARDRAIL_POLICY.version == "out-of-scope-v1"
    assert is_out_of_scope_query("空调出现故障") is True
    assert is_out_of_scope_query("扫地机器人如何清洁滤网") is False


def test_guardrail_policy_can_be_replaced_without_global_mutation() -> None:
    custom = GuardrailPolicy(version="test-v1", unsupported_terms=("咖啡机",))

    assert is_out_of_scope_query("咖啡机漏水", custom) is True
    assert is_out_of_scope_query("空调出现故障", custom) is False
    assert is_out_of_scope_query("空调出现故障") is True


@pytest.mark.parametrize(
    "version,terms",
    [("", ("term",)), ("v1", ())],
)
def test_guardrail_policy_rejects_unversioned_or_empty_terms(
    version: str, terms: tuple[str, ...]
) -> None:
    with pytest.raises(ValueError):
        GuardrailPolicy(version=version, unsupported_terms=terms)
