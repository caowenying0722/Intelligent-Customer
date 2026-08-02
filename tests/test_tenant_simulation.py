from __future__ import annotations

from model.gateway import ModelGateway
from scripts.run_tenant_simulation import (
    SimulationConfig,
    build_prompt,
    build_synthetic_fixtures,
    retrieve,
    run_simulation,
)


def test_synthetic_fixtures_are_deterministic_and_tenant_scoped() -> None:
    config = SimulationConfig(
        tenants=2, documents_per_tenant=5, queries_per_tenant=4, max_calls=8
    )
    documents_a, queries_a = build_synthetic_fixtures(config)
    documents_b, queries_b = build_synthetic_fixtures(config)

    assert documents_a == documents_b
    assert queries_a == queries_b
    for query in queries_a:
        retrieved = retrieve(documents_a, query)
        assert retrieved
        assert {document.tenant_id for document in retrieved} == {query.tenant_id}
        assert all(
            query.tenant_id in build_prompt(query, retrieved, max_chars=4000)
            for _ in [0]
        )


def test_live_simulation_uses_fake_gateway_and_enforces_total_budget(
    monkeypatch,
) -> None:
    gateway = ModelGateway(
        {"anthropic": lambda _prompt: "30 days support-001@example.test"},
        timeout_seconds=1,
        max_retries=0,
        max_concurrency=2,
    )
    monkeypatch.setattr(
        "scripts.run_tenant_simulation._build_live_gateway",
        lambda _config: (gateway, "fake-model", "https://fake.invalid"),
    )
    config = SimulationConfig(
        tenants=2,
        documents_per_tenant=3,
        queries_per_tenant=4,
        max_calls=5,
        max_workers=2,
    )

    report = run_simulation(config, live=True)

    summary = report["summary"]
    assert summary["provider_calls"] == 5
    assert summary["completed"] == 5
    assert summary["budget_exhausted"] == 3
    assert summary["leakage"] == 0
    assert all("response" not in row for row in report["rows"])


def test_dry_run_never_calls_provider() -> None:
    config = SimulationConfig(
        tenants=1, documents_per_tenant=2, queries_per_tenant=2, max_calls=2
    )
    report = run_simulation(config, live=False)

    assert report["summary"]["provider_calls"] == 0
    assert report["summary"]["completed"] == 0
    assert report["summary"]["rows"] == 2
    assert all(row["status"] == "dry_run" for row in report["rows"])
