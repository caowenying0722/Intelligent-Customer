"""Run a bounded, model-free API → Celery → Qdrant ingestion smoke."""

from __future__ import annotations

import argparse
import base64
import json
import time
import urllib.error
import urllib.request
from typing import Any
from uuid import uuid4


def request_json(
    url: str,
    *,
    method: str = "GET",
    tenant_id: str,
    body: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    headers = {"x-tenant-id": tenant_id}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["content-type"] = "application/json"
    if idempotency_key is not None:
        headers["idempotency-key"] = idempotency_key
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            value = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("worker smoke HTTP request failed") from exc
    if not isinstance(value, dict):
        raise RuntimeError("worker smoke received an invalid response")
    return value


def wait_for_job(
    base_url: str,
    *,
    tenant_id: str,
    job_id: str,
    deadline_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        job = request_json(f"{base_url}/api/v1/jobs/{job_id}", tenant_id=tenant_id)
        if job.get("status") in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.25)
    raise RuntimeError("worker smoke job polling timed out")


def run_smoke(base_url: str, *, deadline_seconds: float = 60.0) -> dict[str, str]:
    base_url = base_url.rstrip("/")
    tenant_id = f"worker-smoke-{uuid4().hex[:12]}"
    version = f"smoke-{uuid4().hex[:12]}"
    uploaded = request_json(
        f"{base_url}/api/v1/documents",
        method="POST",
        tenant_id=tenant_id,
        idempotency_key=f"document-{uuid4().hex}",
        body={
            "filename": "worker-smoke.txt",
            "content_base64": base64.b64encode(
                b"model-free Celery ingestion smoke"
            ).decode(),
            "content_type": "text/plain",
            "index_version": version,
        },
    )
    document_id = str(uploaded["document_id"])
    try:
        document_job = wait_for_job(
            base_url,
            tenant_id=tenant_id,
            job_id=str(uploaded["job_id"]),
            deadline_seconds=deadline_seconds,
        )
        if document_job.get("status") != "completed":
            raise RuntimeError(
                f"document ingestion ended as {document_job.get('status')}"
            )
        if int(document_job.get("attempt", 0)) < 1:
            raise RuntimeError("document ingestion did not persist its attempt")
        document = request_json(
            f"{base_url}/api/v1/documents/{document_id}", tenant_id=tenant_id
        )
        if document.get("status") != "active":
            raise RuntimeError("completed job did not activate document metadata")
        rebuild = request_json(
            f"{base_url}/api/v1/indexes/rebuild",
            method="POST",
            tenant_id=tenant_id,
            idempotency_key=f"index-{uuid4().hex}",
            body={"index_version": version},
        )
        rebuild_job = wait_for_job(
            base_url,
            tenant_id=tenant_id,
            job_id=str(rebuild["job_id"]),
            deadline_seconds=deadline_seconds,
        )
        if rebuild_job.get("status") != "completed":
            raise RuntimeError(f"index rebuild ended as {rebuild_job.get('status')}")
        if int(rebuild_job.get("attempt", 0)) < 1:
            raise RuntimeError("index rebuild did not persist its attempt")
        return {
            "tenant_id": tenant_id,
            "document_job": "completed",
            "document_status": "active",
            "index_job": "completed",
            "model_calls": "0",
        }
    finally:
        try:
            request_json(
                f"{base_url}/api/v1/documents/{document_id}",
                method="DELETE",
                tenant_id=tenant_id,
            )
        except RuntimeError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--deadline-seconds", type=float, default=60.0)
    args = parser.parse_args()
    if args.deadline_seconds <= 0:
        parser.error("--deadline-seconds must be positive")
    print(
        json.dumps(
            run_smoke(args.base_url, deadline_seconds=args.deadline_seconds),
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
