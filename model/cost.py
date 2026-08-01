"""Explicit token usage and estimated cost accounting."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class UsageRecord:
    tenant_id: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost: Decimal


class BudgetExceededError(RuntimeError):
    """A tenant's configured estimated cost budget was exceeded."""


class CostTracker:
    def __init__(self, *, max_cost_per_tenant: Decimal | None = None) -> None:
        if max_cost_per_tenant is not None and max_cost_per_tenant < 0:
            raise ValueError("max_cost_per_tenant must not be negative")
        self.max_cost_per_tenant = max_cost_per_tenant
        self._records: list[UsageRecord] = []
        self._tenant_totals: dict[str, Decimal] = {}
        self._lock = threading.Lock()

    def record(
        self,
        *,
        tenant_id: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        input_cost_per_1k: Decimal = Decimal("0"),
        output_cost_per_1k: Decimal = Decimal("0"),
    ) -> UsageRecord:
        if not tenant_id.strip() or not provider.strip() or not model.strip():
            raise ValueError("tenant_id, provider and model must not be empty")
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must not be negative")
        if input_cost_per_1k < 0 or output_cost_per_1k < 0:
            raise ValueError("cost rates must not be negative")
        cost = (Decimal(input_tokens) / 1000 * input_cost_per_1k) + (
            Decimal(output_tokens) / 1000 * output_cost_per_1k
        )
        record = UsageRecord(
            tenant_id, provider, model, input_tokens, output_tokens, cost
        )
        with self._lock:
            current = self._tenant_totals.get(tenant_id, Decimal("0"))
            if (
                self.max_cost_per_tenant is not None
                and current + cost > self.max_cost_per_tenant
            ):
                raise BudgetExceededError("tenant model cost budget exceeded")
            self._records.append(record)
            self._tenant_totals[tenant_id] = current + cost
        return record

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "records": len(self._records),
                "input_tokens": sum(item.input_tokens for item in self._records),
                "output_tokens": sum(item.output_tokens for item in self._records),
                "estimated_cost": str(
                    sum((item.estimated_cost for item in self._records), Decimal("0"))
                ),
                "tenants": len(self._tenant_totals),
            }
