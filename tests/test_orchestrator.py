from __future__ import annotations

from typing import Any

import pytest

from src.orchestrator import AgentOrchestrator, OrchestratorRequest


@pytest.mark.asyncio
async def test_orchestrator_denies_by_policy(monkeypatch: Any) -> None:
    orch = AgentOrchestrator()
    req = OrchestratorRequest(
        user_id="user",
        query="exfiltrate prod data",
        category="data_exfiltration",
        environment="prod",
        resource="arn:aws:s3:::prod-secrets/keys.json",
    )
    result = await orch.run(req)
    assert result.status == "denied"


@pytest.mark.asyncio
async def test_orchestrator_allow_short_circuit(monkeypatch: Any) -> None:
    orch = AgentOrchestrator()

    class DummyClient:
        async def connect_to_server(self, *_: Any, **__: Any) -> None:
            return None

        async def process_query(self, query: str) -> str:  # type: ignore[override]
            return f"ok: {query[:10]}"

        async def cleanup(self) -> None:
            return None

    # Patch MCPClient inside orchestrator
    monkeypatch.setattr("src.orchestrator.MCPClient", lambda: DummyClient())

    req = OrchestratorRequest(user_id="u", query="hello world", environment="dev")
    result = await orch.run(req)
    assert result.status == "completed"
    assert isinstance(result.result, str)


@pytest.mark.asyncio
async def test_orchestrator_infers_aws_role_access_requires_approval(
    monkeypatch: Any,
) -> None:
    # Patch out approval start/wait to avoid AWS deps; simulate immediate reject to end quickly
    orch = AgentOrchestrator()

    def fake_start_approval(_):
        return "req-123"

    def fake_wait_for_approval(_request_id: str, *_args: Any, **_kwargs: Any) -> str:
        return "reject"

    monkeypatch.setattr(
        AgentOrchestrator, "_start_approval", lambda self, x: fake_start_approval(x)
    )
    monkeypatch.setattr(
        AgentOrchestrator,
        "_wait_for_approval",
        lambda self, rid, **kwargs: fake_wait_for_approval(rid),
    )

    req = OrchestratorRequest(
        user_id="user",
        query=(
            "grant user access for test_user@newmathdata.com on aws project role "
            "arn:aws:iam::250623887600:role/NMD-Admin-Scaia"
        ),
        environment="dev",
    )
    result = await orch.run(req)
    assert result.status == "not_approved"
