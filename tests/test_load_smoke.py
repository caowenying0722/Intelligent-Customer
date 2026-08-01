import asyncio

import pytest

from scripts.run_load_smoke import run


def test_bounded_fake_load_smoke_has_no_errors() -> None:
    result = asyncio.run(run(requests=8, concurrency=2))

    assert result["completed"] == 8
    assert result["errors"] == 0
    assert result["model_mode"] == "fake"
    assert result["latency_ms"]["p95"] >= result["latency_ms"]["p50"]


def test_load_smoke_rejects_unbounded_parameters() -> None:
    with pytest.raises(ValueError):
        asyncio.run(run(requests=0, concurrency=1))
    with pytest.raises(ValueError):
        asyncio.run(run(requests=2, concurrency=3))
