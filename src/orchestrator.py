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
import logging

import boto3
from pydantic import BaseModel, Field

from .approval_handler import (
    ApprovalItem,
    get_approval_status,
    handle_new_approval_request,
    compute_request_id_from_action,
)
from .config_store import get_policies
from .mcp_client import invoke_mcp_client
from .memory import ShortTermMemory
from .policy import (
    ApprovalOutcome,
    PolicyEngine,
    ProposedAction,
)

logging.basicConfig(
    level=logging.INFO,
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
    # Optional list of fully-qualified tool ids the agent expects to use
    intended_tools: list[str] = Field(default_factory=list)


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
        # Load rules from config DB when available; fall back to default
        if policy_engine is not None:
            self.policy_engine = policy_engine
        else:
            try:
                cfg = get_policies()
                rules = cfg.rules if cfg.rules else None
            except Exception:
                rules = None
            self.policy_engine = PolicyEngine(rules=rules)
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
        request_id = compute_request_id_from_action(request.query)
        if existing_approval_item := get_approval_status(request_id):
            decision = existing_approval_item.approval_status
        else:
            request_id, decision = self._start_approval(request)
        if decision == ApprovalOutcome.DENY:
            return OrchestratorResult(
                status="denied", message=decision.rationale
            )


        if decision == ApprovalOutcome.ALLOW:
            return await self._execute_direct(request, approval_request_id=request_id)

        # REQUIRE_APPROVAL path
        self.memory.append(
            "system",
            (
                "Approval requested for: "
                f"{request.query} (id={request_id})"
            ),
        )

        status = self._wait_for_approval(request_id)
        if status != ApprovalOutcome.ALLOW:
            return OrchestratorResult(
                status="not_approved",
                request_id=request_id,
                message=f"Approval status: {status}",
            )

        result = await self._execute_direct(request, approval_request_id=request_id)
        result.request_id = request_id
        return result

    async def _execute_direct(
        self, request: OrchestratorRequest, approval_request_id: str | None = None
    ) -> OrchestratorResult:
        """Execute the request through the MCP client directly."""

        prompt_prefix = self.memory.as_prompt_prefix()
        full_query = (
            f"{prompt_prefix}\n\nUser request: {request.query}"
            if prompt_prefix
            else request.query
        )
        print(f"Getting approval status for request_id: {approval_request_id}")
        if approval_request_id:
            try:
                item = get_approval_status(approval_request_id)
            except Exception:
                pass
        if not item.allowed_tools:
            raise ValueError(f"No allowed tools found for request_id: {approval_request_id}")
        print(f"Allowed tools: {item.allowed_tools}")
        response_text = await invoke_mcp_client(full_query, request.user_id, item.allowed_tools)

        self.memory.append("user", request.query)
        self.memory.append("assistant", response_text)
        return OrchestratorResult(status="completed", result=response_text)

    def _start_approval(self, proposed: ProposedAction) -> str:
        """Trigger Step Functions approval workflow; return request_id."""
        resp = handle_new_approval_request(
            {
                "requester": proposed.user_id or "unknown",
                "approver": "",
                "agent_prompt": proposed.query,
                "proposed_action": proposed.query,
                "reason": "Policy requires approval",
                "proposed_tool": proposed.tool_name,
                "approval_status":ApprovalOutcome.REQUIRE_APPROVAL,
            }
        )
        try:
            created_id = resp.get("body", {}).get("request_id")  # type: ignore[union-attr]
        except Exception:
            created_id = None
         
        return created_id, resp.get("body", {}).get("status")


    def _wait_for_approval(
        self,
        request_id: str,
        timeout_seconds: int = 1800,
        poll_interval: int = 10,
    ) -> str:
        """Poll approval status in DynamoDB via approval_handler helper."""

        deadline = time.time() + timeout_seconds

        while time.time() < deadline:
            item = get_approval_status(request_id)
            if item and item.approval_status in {
                ApprovalOutcome.ALLOW,
                ApprovalOutcome.DENY,
            }:

                return item.approval_status

            time.sleep(poll_interval)
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
