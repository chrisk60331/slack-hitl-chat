from __future__ import annotations

import os
import asyncio
from typing import Any

import pytest

from src.orchestrator import AgentOrchestrator, OrchestratorRequest


@pytest.mark.asyncio
async def test_orchestrator_sets_allowlist_from_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "us-west-2")

    class DummyApprovalItem:
        def __init__(self) -> None:
            self.allowed_tools = ["alias__foo"]

    # Always report approval ALLOW and provide allowed_tools
    from src import approval_handler

    monkeypatch.setattr(
        approval_handler, "get_approval_status", lambda rid: DummyApprovalItem()
    )

    orch = AgentOrchestrator()

    # Short-circuit approval flow and execution
    async def fake_execute_direct(request: OrchestratorRequest, approval_request_id: str | None = None):
        # The env var should be set inside _execute_direct
        assert os.getenv("MCP_ALLOWED_TOOLS") == "alias__foo"
        class R:
            status = "completed"
            result = "ok"
        return R()

    monkeypatch.setattr(orch, "_start_approval", lambda proposed: "rid")
    monkeypatch.setattr(orch, "_wait_for_approval", lambda rid: "allow")
    monkeypatch.setattr(orch, "_execute_direct", fake_execute_direct)

    req = OrchestratorRequest(user_id="u", query="q", intended_tools=["alias__foo"])
    res = await orch.run(req)
    assert res.status == "completed"

