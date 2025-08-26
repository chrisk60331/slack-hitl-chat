"""Higher-level AgentCore orchestrator with HITL approval guard.

This module wraps the existing approval and execution handlers and the MCP
client without changing their internal behavior. It decides whether a given
proposed action may proceed directly, requires approval via Step Functions, or
should be denied by policy.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import boto3
from pydantic import BaseModel, Field

from .approval_handler import ApprovalItem, get_approval_status
from .mcp_client import MCPClient
from .memory import ShortTermMemory
from .policy import (
    ApprovalCategory,
    ApprovalOutcome,
    PolicyDecision,
    PolicyEngine,
    ProposedAction,
    infer_category_and_resource,
)


class OrchestratorRequest(BaseModel):
    """Input for orchestrator runs."""

    user_id: str
    query: str
    tool_name: str | None = None
    category: str | None = None
    resource: str | None = None
    amount: float | None = None
    environment: str = Field(
        default_factory=lambda: os.getenv("ENVIRONMENT", "dev")
    )


class OrchestratorResult(BaseModel):
    """Result of orchestrator run."""

    status: str
    request_id: str | None = None
    result: Any | None = None
    message: str | None = None


@dataclass(slots=True)
class AgentOrchestrator:
    """Coordinates policy decisions, HITL approvals, and MCP execution."""

    memory: ShortTermMemory
    policy_engine: PolicyEngine
    _sfn_client: Any | None = field(init=False, repr=False, default=None)
    _hitl_sfn_arn: str = field(init=False, repr=False, default="")

    def __init__(
        self,
        memory: ShortTermMemory | None = None,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self.memory = memory or ShortTermMemory()
        self.policy_engine = policy_engine or PolicyEngine()
        self._sfn_client = boto3.client(
            "stepfunctions", region_name=os.getenv("AWS_REGION")
        )
        self._hitl_sfn_arn = os.getenv("APPROVAL_SFN_ARN", "")

    async def run(self, request: OrchestratorRequest) -> OrchestratorResult:
        """Handle a single user query end-to-end with HITL guarding.

        Behavior:
        - Build a ProposedAction from the request
        - Evaluate policy
        - If allow → call MCP directly
        - If require_approval → start SFN and wait for approval status,
          then execute
        - If deny → return denied status
        """

        # Infer category/resource when not provided
        inferred_category: ApprovalCategory = ApprovalCategory.OTHER
        inferred_resource: str | None = None
        if not request.category or not request.resource:
            inferred_category, inferred_resource = infer_category_and_resource(
                request.query
            )

        proposed = ProposedAction(
            tool_name=request.tool_name or "auto",
            description=request.query,
            category=(
                self._coerce_category(request.category)
                if request.category
                else inferred_category
            ),
            resource=request.resource or inferred_resource,
            amount=request.amount,
            environment=request.environment,
            user_id=request.user_id,
        )

        decision: PolicyDecision = self.policy_engine.evaluate(proposed)

        print(f"Decision: {decision}")

        if decision.outcome == ApprovalOutcome.DENY:
            return OrchestratorResult(
                status="denied", message=decision.rationale
            )

        if decision.outcome == ApprovalOutcome.ALLOW:
            return await self._execute_direct(request)

        # REQUIRE_APPROVAL path
        request_id = self._start_approval(proposed)
        self.memory.append(
            "system",
            (
                "Approval requested for: "
                f"{proposed.description} (id={request_id})"
            ),
        )

        status = self._wait_for_approval(request_id)
        if status != ApprovalOutcome.ALLOW:
            return OrchestratorResult(
                status="not_approved",
                request_id=request_id,
                message=f"Approval status: {status}",
            )

        result = await self._execute_direct(request)
        result.request_id = request_id
        return result

    async def _execute_direct(
        self, request: OrchestratorRequest
    ) -> OrchestratorResult:
        """Execute the request through the MCP client directly."""

        prompt_prefix = self.memory.as_prompt_prefix()
        full_query = (
            f"{prompt_prefix}\n\nUser request: {request.query}"
            if prompt_prefix
            else request.query
        )

        client = MCPClient()
        try:
            servers_env = os.getenv("MCP_SERVERS", "").strip()
            if servers_env:
                # Auto-connect handled in process_query, but we connect
                # explicitly to fail fast on misconfig
                alias_to_path = {}
                for part in servers_env.split(";"):
                    if not part or "=" not in part:
                        continue
                    alias, path = part.split("=", 1)
                    alias_to_path[alias.strip()] = path.strip()
                if alias_to_path:
                    await client.connect_to_servers(
                        alias_to_path, request.user_id
                    )
            else:
                await client.connect_to_server(
                    "google_mcp/google_admin/mcp_server.py"
                )
            response_text = await client.process_query(
                full_query, request.user_id
            )
        finally:
            await client.cleanup()

        self.memory.append("user", request.query)
        self.memory.append("assistant", response_text)
        return OrchestratorResult(status="completed", result=response_text)

    def _start_approval(self, proposed: ProposedAction) -> str:
        """Trigger Step Functions approval workflow; return request_id."""

        if not self._hitl_sfn_arn:
            # Fallback: directly call approval_handler lambda input format
            # locally
            item = ApprovalItem(
                requester=proposed.user_id or "unknown",
                approver="",
                agent_prompt=proposed.description,
                proposed_action=proposed.description,
                reason="Policy requires approval",
                approval_status="pending",
            )
            # Persist via table put through approval_handler path
            # We avoid direct table access here to preserve encapsulation.
            # approval_handler._handle_new_approval_request expects
            # event-like dict
            from .approval_handler import _handle_new_approval_request

            resp = _handle_new_approval_request(
                {
                    "requester": item.requester,
                    "approver": item.approver,
                    "agent_prompt": item.agent_prompt,
                    "proposed_action": item.proposed_action,
                    "reason": item.reason,
                    "approval_status": item.approval_status,
                }
            )
            try:
                created_id = resp.get("body", {}).get(
                    "request_id"
                )  # type: ignore[union-attr]
                print(

                        "Approval created: local_request_id="
                        f"{item.request_id} handler_request_id={created_id}"

                )
            except Exception:
                created_id = None
                # Best-effort diagnostic; do not change behavior if response
                # format differs
                print(

                        "Approval created: local_request_id="
                        f"{item.request_id} (handler response not loggable)"

                )
            # Use handler-generated id when available so polling matches the
            # stored record
            return created_id or item.request_id

        input_payload: dict[str, Any] = {
            "requester": proposed.user_id or "unknown",
            "approver": "",
            "agent_prompt": proposed.description,
            "proposed_action": proposed.description,
            "reason": "Policy requires approval",
            "approval_status": "pending",
        }

        self._sfn_client.start_execution(
            stateMachineArn=self._hitl_sfn_arn,
            input=json.dumps(input_payload),
        )

        # The approval lambda generates the request_id; we need to fetch it
        # to poll status. In this simplified flow, we rely on the proposed
        # content lookup not being feasible, so we re-query by latest item is
        # not available. Instead, we return a synthetic id by storing locally
        # when not using Step Functions. For SFN flow, real systems should
        # return the id from the first task. Here we fall back to asking the
        # status by other means. To avoid changing existing handlers, we
        # generate a client-side id for tracking logs only.
        return "sfn-exec"

    def _wait_for_approval(
        self,
        request_id: str,
        timeout_seconds: int = 1800,
        poll_interval: int = 10,
    ) -> str:
        """Poll approval status in DynamoDB via approval_handler helper."""

        deadline = time.time() + timeout_seconds
        print(

                "Starting approval polling: "
                f"request_id={request_id} timeout_seconds={timeout_seconds} "
                f"poll_interval={poll_interval}"

        )
        while time.time() < deadline:
            item = get_approval_status(request_id)
            if item and item.approval_status in {
                ApprovalOutcome.ALLOW,
                ApprovalOutcome.DENY,
            }:
                print(

                        "Approval item found: "
                        f"request_id={request_id} status={item.approval_status}"

                )
                return item.approval_status
            print(

                    "Approval not yet decided for "
                    f"request_id={request_id}; sleeping {poll_interval}s"

            )
            time.sleep(poll_interval)
        print(f"Approval polling timed out for request_id={request_id}")
        return "timeout"

    @staticmethod
    def _coerce_category(category: str | None):
        from .policy import ApprovalCategory

        if not category:
            return ApprovalCategory.OTHER
        try:
            return ApprovalCategory(category)
        except ValueError:
            return ApprovalCategory.OTHER
