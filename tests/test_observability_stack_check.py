import io
import json

import pytest

from scripts.check_observability_stack import check


class Response:
    status = 200

    def __init__(self, payload: dict) -> None:
        self._body = io.BytesIO(json.dumps(payload).encode())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._body.read()


def test_observability_check_requires_healthy_scrape_and_backends(monkeypatch) -> None:
    def urlopen(url: str, timeout: float):
        assert timeout == 2
        if url.endswith("/health/live"):
            return Response({"status": "ok"})
        if url.endswith(":13133/"):
            return Response({"status": "Server available"})
        if url.endswith("/api/v1/targets"):
            return Response(
                {
                    "data": {
                        "activeTargets": [
                            {
                                "health": "up",
                                "scrapeUrl": "http://api:8000/metrics/prometheus",
                            }
                        ]
                    }
                }
            )
        return Response({"database": "ok"})

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    assert check(timeout=2) == {
        "api": "ok",
        "collector": "ok",
        "prometheus": "ok",
        "grafana": "ok",
    }


def test_observability_check_fails_closed_without_scrape_target(monkeypatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda url, timeout: Response({"data": {}})
    )
    with pytest.raises(RuntimeError):
        check()
