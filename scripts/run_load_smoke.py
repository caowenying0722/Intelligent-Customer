"""Run a bounded in-process API load smoke with a fake Agent."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx

from src.app.application.chat import ChatApplicationService
from src.app.main import create_app


class FakeLoadAgent:
    def run(self, message: str) -> str:
        return f"echo:{message}"

    def stream(self, message: str) -> list[str]:
        return [f"echo:{message}"]


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((percentile / 100) * (len(ordered) - 1)))
    return ordered[index]


async def run(requests: int = 20, concurrency: int = 4) -> dict[str, Any]:
    if requests < 1 or requests > 1000:
        raise ValueError("requests must be between 1 and 1000")
    if concurrency < 1 or concurrency > requests:
        raise ValueError("concurrency must be between 1 and requests")
    app = create_app(chat_service=ChatApplicationService(FakeLoadAgent()))
    limits = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    statuses: list[int] = []

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:

        async def one(index: int) -> None:
            async with limits:
                started = time.perf_counter()
                try:
                    response = await asyncio.wait_for(
                        client.post("/api/v1/chat", json={"message": f"smoke-{index}"}),
                        timeout=10,
                    )
                    statuses.append(response.status_code)
                except (TimeoutError, asyncio.TimeoutError):
                    statuses.append(599)
                finally:
                    latencies.append((time.perf_counter() - started) * 1000)

        started = time.perf_counter()
        await asyncio.gather(*(one(index) for index in range(requests)))
        elapsed = time.perf_counter() - started

    errors = sum(status >= 400 for status in statuses)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "requests": requests,
        "concurrency": concurrency,
        "completed": len(statuses),
        "errors": errors,
        "error_rate": errors / requests,
        "throughput_rps": requests / elapsed if elapsed else 0.0,
        "latency_ms": {
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
        },
        "status_counts": {
            str(status): statuses.count(status) for status in sorted(set(statuses))
        },
        "model_mode": "fake",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--output", default="output/load-smoke.json")
    args = parser.parse_args()
    result = asyncio.run(run(args.requests, args.concurrency))
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(destination)
    return 0 if result["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
