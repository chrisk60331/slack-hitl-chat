"""FastAPI wrapper exposing orchestrator endpoints.

This wraps existing code paths and does not modify existing handlers.
"""

from __future__ import annotations

import os
import json
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from .orchestrator import AgentOrchestrator, OrchestratorRequest


app = FastAPI(title="AgentCore Orchestrator API")
_orchestrator = AgentOrchestrator()


class RunPayload(BaseModel):
    user_id: str
    query: str
    tool_name: str | None = None
    category: str | None = None
    resource: str | None = None
    amount: float | None = None
    environment: str | None = None


@app.post("/agent/run")
async def start_run(payload: RunPayload) -> Dict[str, Any]:
    req = OrchestratorRequest(**payload.model_dump())
    result = await _orchestrator.run(req)
    return result.model_dump()


@app.get("/healthz")
async def healthz() -> Dict[str, str]:
    return {"status": "ok", "env": os.getenv("ENVIRONMENT", "dev")}


@app.post("/slack/interactions")
async def slack_interactions(request: Request) -> Dict[str, str]:
    """Slack interactivity endpoint for Block Kit button actions.

    Verifies Slack signature, parses payload, applies approval decision,
    and updates the original message via response_url.
    """
    raw_body: bytes = await request.body()
    signature = request.headers.get("X-Slack-Signature", "")
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")

    from .slack_helper import verify_slack_request, parse_action_from_interaction, respond_via_response_url
    from .approval_handler import _handle_approval_decision

    signing_secret = os.getenv("SLACK_SIGNING_SECRET", "")
    if not verify_slack_request(signing_secret, timestamp, raw_body, signature):
        raise HTTPException(status_code=401, detail="invalid signature")

    form = await request.form()
    payload_str = form.get("payload")
    if not payload_str:
        raise HTTPException(status_code=400, detail="missing payload")

    try:
        payload = json.loads(payload_str)
    except Exception as e:  # pragma: no cover - defensive
        raise HTTPException(status_code=400, detail=f"invalid payload: {e}")

    request_id, action, user_id = parse_action_from_interaction(payload)

    # Apply approval decision via existing handler
    event = {"body": {"request_id": request_id, "action": action, "approver": user_id, "reason": "via Slack"}}
    _ = _handle_approval_decision(event)

    # Update original message
    response_url = payload.get("response_url", "")
    status_text = f"Request {request_id} {action} by <@{user_id}>"
    if response_url:
        try:
            respond_via_response_url(response_url, status_text)
        except Exception:
            pass

    return {"status": "ok"}

