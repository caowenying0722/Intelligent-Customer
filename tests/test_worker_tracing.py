import time

from src.app.application.ingestion import IngestionJobManager, IngestionJobStatus
from src.app.observability.tracing import ApiTracer


def _wait_for(manager, tenant_id, job_id):
    for _ in range(100):
        job = manager.get(tenant_id=tenant_id, job_id=job_id)
        if job is not None and job.status != IngestionJobStatus.QUEUED:
            return job
        time.sleep(0.01)
    raise AssertionError("worker job did not finish")


def test_worker_captures_parent_context_without_job_or_tenant_attributes():
    tracer = ApiTracer(max_spans=8)
    manager = IngestionJobManager(max_workers=1, tracer=tracer)
    try:
        with tracer.start_span("parent.request") as parent:
            expected_trace_id = f"{parent.get_span_context().trace_id:032x}"
            job = manager.submit(
                tenant_id="tenant-secret",
                idempotency_key="trace-job",
                operation=lambda: "ok",
            )
            assert (
                _wait_for(manager, "tenant-secret", job.job_id).status
                == IngestionJobStatus.COMPLETED
            )

        spans = tracer.exporter.snapshot()
        worker_spans = [span for span in spans if span["name"] == "worker.ingestion"]
        assert worker_spans
        assert worker_spans[-1]["trace_id"] == expected_trace_id
        assert "tenant-secret" not in str(spans)
        assert str(job.job_id) not in str(spans)
    finally:
        manager.close()
        tracer.close()
