from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, MessagesState, StateGraph

from src.app.application.ingestion import IngestionJob, IngestionJobStatus
from src.app.domain.approvals import ApprovalRequired
from src.app.infrastructure.checkpoints import PostgresCheckpointRuntime
from src.app.infrastructure.ingestion import SqlAlchemyIngestionRepository
from src.app.server import build_server_app
from utils.settings import Settings

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL, reason="TEST_POSTGRES_URL is required for PostgreSQL integration"
)


def _checkpoint_graph(checkpointer: object):
    def respond(state: MessagesState):
        return {"messages": [AIMessage(content=f"seen:{len(state['messages'])}")]}

    builder = StateGraph(MessagesState)
    builder.add_node("respond", respond)
    builder.add_edge(START, "respond")
    builder.add_edge("respond", END)
    return builder.compile(checkpointer=checkpointer)  # type: ignore[arg-type]


def test_postgres_checkpoint_survives_runtime_restart() -> None:
    assert POSTGRES_URL is not None
    thread_id = f"integration-{uuid4().hex}"
    config = {"configurable": {"thread_id": thread_id}}

    first = PostgresCheckpointRuntime(POSTGRES_URL, pool_size=2)
    first.start()
    _checkpoint_graph(first.checkpointer).invoke(
        {"messages": [{"role": "user", "content": "one"}]}, config
    )
    first.close()

    second = PostgresCheckpointRuntime(POSTGRES_URL, pool_size=2)
    second.start()
    result = _checkpoint_graph(second.checkpointer).invoke(
        {"messages": [{"role": "user", "content": "two"}]}, config
    )
    second.checkpointer.delete_thread(thread_id)
    second.close()

    assert len(result["messages"]) == 4
    assert result["messages"][-1].content == "seen:3"


class FakeAgent:
    def run(self, message: str) -> str:
        return f"persisted:{message}"

    def stream(self, message: str) -> list[str]:
        return [self.run(message)]


def test_server_composition_uses_postgres_across_restart() -> None:
    assert POSTGRES_URL is not None
    tenant_id = f"tenant-{uuid4().hex}"
    settings = Settings.model_validate(
        {"database_url": POSTGRES_URL, "request_timeout_seconds": 5}
    )

    with TestClient(build_server_app(FakeAgent(), settings=settings)) as first:
        created = first.post(
            "/api/v1/chat",
            json={"message": "remember"},
            headers={"x-tenant-id": tenant_id, "x-user-id": "integration-user"},
        )
        assert created.status_code == 200

    with TestClient(build_server_app(FakeAgent(), settings=settings)) as second:
        recovered = second.get(
            f"/api/v1/conversations/{created.json()['conversation_id']}",
            headers={"x-tenant-id": tenant_id},
        )

    assert recovered.status_code == 200
    assert [item["content"] for item in recovered.json()["messages"]] == [
        "remember",
        "persisted:remember",
    ]


class InterruptingAgent:
    def run(self, _message: str) -> str:
        raise AssertionError("thread-aware path required")

    def stream(self, _message: str) -> list[str]:
        raise AssertionError("thread-aware path required")

    def run_in_thread(self, _message: str, _thread_id: str) -> str:
        raise ApprovalRequired(
            interrupt_id=f"interrupt-{uuid4().hex}",
            tool_name="mutate",
            arguments={"value": "x"},
        )

    def resume_in_thread(
        self, _thread_id: str, *, approved: bool, approval_id: str
    ) -> str:
        assert approved is True
        assert approval_id
        return "resumed-after-restart"


def test_postgres_approval_survives_application_restart() -> None:
    assert POSTGRES_URL is not None
    tenant_id = f"tenant-{uuid4().hex}"
    settings = Settings.model_validate({"database_url": POSTGRES_URL})

    with TestClient(build_server_app(InterruptingAgent(), settings=settings)) as first:
        pending = first.post(
            "/api/v1/chat",
            json={"message": "change"},
            headers={"x-tenant-id": tenant_id},
        )
        assert pending.status_code == 202
        approval_id = pending.json()["approval_id"]

    with TestClient(build_server_app(InterruptingAgent(), settings=settings)) as second:
        resumed = second.post(
            f"/api/v1/approvals/{approval_id}/decision",
            json={"approved": True},
            headers={"x-tenant-id": tenant_id, "x-user-id": "approver"},
        )

    assert resumed.status_code == 200
    assert resumed.json()["execution_status"] == "completed"
    assert resumed.json()["answer"] == "resumed-after-restart"


def test_postgres_workers_claim_job_once_with_skip_locked() -> None:
    assert POSTGRES_URL is not None
    tenant_id = f"tenant-{uuid4().hex}"
    job = IngestionJob(
        job_id=uuid4(),
        tenant_id=tenant_id,
        idempotency_key=f"claim-{uuid4().hex}",
        status=IngestionJobStatus.QUEUED,
        created_at=datetime.now(timezone.utc),
    )
    creator = SqlAlchemyIngestionRepository(POSTGRES_URL)
    creator.create_job(job=job)
    creator.close()
    barrier = Barrier(2)

    def claim(worker_id: str):
        repository = SqlAlchemyIngestionRepository(POSTGRES_URL)
        try:
            barrier.wait(timeout=5)
            return repository.claim_recoverable_jobs(
                worker_id=worker_id,
                lease_seconds=30,
                tenant_id=tenant_id,
                limit=1,
            )
        finally:
            repository.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ["worker-1", "worker-2"]))

    winners = [lease for leases in results for lease in leases]
    assert len(winners) == 1
    winner = winners[0]
    finisher = SqlAlchemyIngestionRepository(POSTGRES_URL)
    completed = finisher.complete_claimed_job(
        tenant_id=tenant_id,
        job_id=job.job_id,
        worker_id=winner.worker_id,
        lease_token=winner.lease_token,
        fence_version=winner.fence_version,
        status=IngestionJobStatus.COMPLETED,
    )
    finisher.close()
    assert completed.status == IngestionJobStatus.COMPLETED
