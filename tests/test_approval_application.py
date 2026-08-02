from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.app.application.approvals import ApprovalApplicationService
from src.app.application.chat import (
    ChatApplicationService,
    ChatApprovalRequired,
)
from src.app.domain.approvals import ApprovalRequired, InMemoryApprovalRepository
from src.app.main import create_app


class InterruptingAgent:
    def __init__(self) -> None:
        self.resume_calls: list[tuple[str, bool, str]] = []

    def run(self, _message: str) -> str:
        raise AssertionError("thread-aware path required")

    def stream(self, _message: str) -> list[str]:
        raise AssertionError("thread-aware path required")

    def run_in_thread(self, _message: str, _thread_id: str) -> str:
        raise ApprovalRequired(
            interrupt_id="interrupt-1",
            tool_name="mutate",
            arguments={"value": "x"},
        )

    def resume_in_thread(
        self, thread_id: str, *, approved: bool, approval_id: str
    ) -> str:
        self.resume_calls.append((thread_id, approved, approval_id))
        return "approved answer"


def _service(agent: InterruptingAgent) -> ChatApplicationService:
    return ChatApplicationService(
        agent,
        approval_service=ApprovalApplicationService(InMemoryApprovalRepository()),
    )


def test_approval_resumes_interrupted_run_once() -> None:
    agent = InterruptingAgent()
    service = _service(agent)

    async def exercise():
        with pytest.raises(ChatApprovalRequired) as caught:
            await service.chat("change", tenant_id="tenant-a")
        approval = caught.value.approval
        run = service.conversation_repository.get_run("tenant-a", approval.run_id)
        assert run is not None and run.status == "interrupted"

        completed, answer = await service.decide_approval(
            "tenant-a",
            approval.approval_id,
            approved=True,
            decided_by="approver-1",
        )
        repeated, repeated_answer = await service.decide_approval(
            "tenant-a",
            approval.approval_id,
            approved=True,
            decided_by="approver-1",
        )
        return approval, completed, answer, repeated, repeated_answer

    approval, completed, answer, repeated, repeated_answer = asyncio.run(exercise())

    assert answer == "approved answer"
    assert completed.status == "approved"
    assert completed.execution_status == "completed"
    assert repeated.execution_status == "completed"
    assert repeated_answer is None
    assert len(agent.resume_calls) == 1
    assert service.approval_service is not None
    assert service.approval_service.get("tenant-b", approval.approval_id) is None
    run = service.conversation_repository.get_run("tenant-a", approval.run_id)
    assert run is not None and run.status == "completed"


def test_rejected_approval_cancels_run_without_tool_resume() -> None:
    agent = InterruptingAgent()
    service = _service(agent)

    async def exercise():
        with pytest.raises(ChatApprovalRequired) as caught:
            await service.chat("change", tenant_id="tenant-a")
        approval, answer = await service.decide_approval(
            "tenant-a",
            caught.value.approval.approval_id,
            approved=False,
            decided_by="approver-1",
        )
        return approval, answer

    approval, answer = asyncio.run(exercise())

    assert approval.status == "rejected"
    assert approval.execution_status == "denied"
    assert answer is None
    assert agent.resume_calls == []
    run = service.conversation_repository.get_run("tenant-a", approval.run_id)
    assert run is not None and run.status == "cancelled"


def test_approval_http_flow_returns_202_then_resumes() -> None:
    agent = InterruptingAgent()
    service = _service(agent)
    client = TestClient(create_app(chat_service=service))

    pending = client.post(
        "/api/v1/chat",
        json={"message": "change"},
        headers={"x-tenant-id": "tenant-a"},
    )

    assert pending.status_code == 202
    assert pending.json()["code"] == "approval_required"
    approval_id = pending.json()["approval_id"]
    fetched = client.get(
        f"/api/v1/approvals/{approval_id}",
        headers={"x-tenant-id": "tenant-a"},
    )
    assert fetched.status_code == 200
    assert fetched.json()["arguments"] == {"value": "x"}

    decided = client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"approved": True},
        headers={"x-tenant-id": "tenant-a", "x-user-id": "approver-1"},
    )

    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"
    assert decided.json()["execution_status"] == "completed"
    assert decided.json()["answer"] == "approved answer"
    assert UUID(approval_id)
