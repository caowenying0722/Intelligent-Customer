from decimal import Decimal

import pytest

from model.cost import CostTracker


def test_cost_tracker_requires_explicit_usage_and_computes_cost():
    tracker = CostTracker()
    record = tracker.record(
        tenant_id="a", provider="fake", model="m", input_tokens=1000,
        output_tokens=500, input_cost_per_1k=Decimal("1"), output_cost_per_1k=Decimal("2"),
    )
    assert record.estimated_cost == Decimal("2.0")
    assert tracker.snapshot()["input_tokens"] == 1000
    assert tracker.snapshot()["estimated_cost"] == "2.0"


@pytest.mark.parametrize("kwargs", [{"input_tokens": -1}, {"output_tokens": -1}])
def test_cost_tracker_rejects_negative_tokens(kwargs):
    with pytest.raises(ValueError):
        CostTracker().record(
            tenant_id="a", provider="fake", model="m",
            input_tokens=kwargs.get("input_tokens", 0),
            output_tokens=kwargs.get("output_tokens", 0),
        )
