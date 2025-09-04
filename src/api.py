"""FastAPI wrapper exposing orchestrator endpoints.

This wraps existing code paths and does not modify existing handlers.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .config_store import (
    MCPServer,
    MCPServersConfig,
    PoliciesConfig,
    get_mcp_servers,
    get_policies,
    put_mcp_servers,
    put_policies,
)
from .dynamodb_utils import get_approval_table
from .mcp_client import MCPClient
from .orchestrator import AgentOrchestrator, OrchestratorRequest

app = FastAPI(title="AgentCore Orchestrator API")
_orchestrator = AgentOrchestrator()
_sessions: dict[str, dict[str, Any]] = {}
logger = logging.getLogger(__name__)
# Mount Flask Admin UI under /admin
try:
    from .flask_ui import create_app as _create_flask_app

    _flask_app = _create_flask_app()
    app.mount("/admin", WSGIMiddleware(_flask_app))
except Exception:
    # If Flask or UI is unavailable, continue without mounting (non-fatal)
    pass


class RunPayload(BaseModel):
    user_id: str
    query: str
    tool_name: str | None = None
    category: str | None = None
    resource: str | None = None
    amount: float | None = None
    environment: str | None = None


# --- Config: MCP servers ---


@app.get("/config/mcp-servers", response_model=MCPServersConfig)
async def list_mcp_servers() -> dict[str, list[dict[str, Any]]]:
    cfg = get_mcp_servers()
    return {"servers": [s.model_dump() for s in cfg.servers]}


class PutServersPayload(BaseModel):
    servers: list[MCPServer]


@app.put("/config/mcp-servers", response_model=MCPServersConfig)
async def replace_mcp_servers(
    payload: PutServersPayload,
) -> dict[str, list[dict[str, Any]]]:
    put_mcp_servers(payload.servers)
    return {"servers": [s.model_dump() for s in payload.servers]}


# --- Config: Policies ---


@app.get("/config/policies", response_model=PoliciesConfig)
async def get_policy_rules() -> dict[str, list[dict[str, Any]]]:
    cfg = get_policies()
    return {"rules": [r.model_dump() for r in cfg.rules]}


class PutPoliciesPayload(BaseModel):
    rules: list[dict[str, Any]]


@app.put("/config/policies", response_model=PoliciesConfig)
async def put_policy_rules(
    payload: PutPoliciesPayload,
) -> dict[str, list[dict[str, Any]]]:
    rules = [
        # validate using PolicyRule model by round-tripping through PoliciesConfig
        # but here directly construct is fine
        # PolicyRule(**r)
        r
        for r in payload.rules
    ]
    # Convert to PolicyRule for storage validation
    from .policy import PolicyRule

    validated = [PolicyRule(**r) for r in rules]
    put_policies(validated)
    return {"rules": [r.model_dump() for r in validated]}


# --- Approvals Audit (read-only) ---


@app.get("/audit/approvals")
async def list_approvals(limit: int = 50) -> dict[str, list[dict[str, Any]]]:
    """Return recent approvals by scanning and sorting by creation timestamp."""
    table = get_approval_table()

    # Paginated scan, gather a buffer larger than limit to ensure recency
    items: list[dict[str, Any]] = []
    start_key: dict[str, Any] | None = None
    max_scan: int = max(limit * 5, 100)
    while True:
        scan_kwargs: dict[str, Any] = {"Limit": min(200, max_scan)}
        if start_key:
            scan_kwargs["ExclusiveStartKey"] = start_key
        resp = table.scan(**scan_kwargs)
        items.extend(resp.get("Items", []))
        start_key = resp.get("LastEvaluatedKey")
        if not start_key or len(items) >= max_scan:
            break

    def _ts_key(d: dict[str, Any]) -> float:
        ts = d.get("timestamp", "")
        try:
            # Normalize Z to +00:00 for Python fromisoformat
            from datetime import datetime

            norm = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(norm).timestamp()
        except Exception:
            return 0.0

    items = sorted(items, key=_ts_key, reverse=True)[:limit]
    return {"items": items}


@app.post("/agent/run")
async def start_run(payload: RunPayload) -> dict[str, Any]:
    req = OrchestratorRequest(**payload.model_dump())
    result = await _orchestrator.run(req)
    return result.model_dump()


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "env": os.getenv("ENVIRONMENT", "dev")}


@app.post("/slack/interactions")
async def slack_interactions(request: Request) -> dict[str, str]:
    """Slack interactivity endpoint for Block Kit button actions.

    Verifies Slack signature, parses payload, applies approval decision,
    and updates the original message via response_url.
    """
    raw_body: bytes = await request.body()
    signature = request.headers.get("X-Slack-Signature", "")
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")

    from .approval_handler import _handle_approval_decision
    from .slack_helper import (
        parse_action_from_interaction,
        respond_via_response_url,
        verify_slack_request,
    )

    signing_secret = os.getenv("SLACK_SIGNING_SECRET", "")
    if not verify_slack_request(
        signing_secret, timestamp, raw_body, signature
    ):
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
    event = {
        "body": {
            "request_id": request_id,
            "action": action,
            "approver": user_id,
            "reason": "via Slack",
        }
    }
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


class CreateSessionResponse(BaseModel):
    session_id: str


class PostMessageRequest(BaseModel):
    query: str
    user_id: str | None = None
    metadata: dict[str, Any] | None = None


class PostMessageResponse(BaseModel):
    message_id: str


def _ensure_session(session_id: str) -> dict[str, Any]:
    store = _sessions.setdefault(session_id, {})
    return store


@app.post("/gateway/v1/sessions", response_model=CreateSessionResponse)
async def create_session() -> dict[str, str]:
    import uuid

    session_id = f"s-{uuid.uuid4().hex[:10]}"
    _ensure_session(session_id)
    return {"session_id": session_id}


@app.post(
    "/gateway/v1/sessions/{session_id}/messages",
    response_model=PostMessageResponse,
)
async def post_message(
    session_id: str, payload: PostMessageRequest
) -> dict[str, str]:
    import asyncio
    import uuid

    store = _ensure_session(session_id)
    message_id = f"m-{uuid.uuid4().hex[:10]}"
    queue: asyncio.Queue[str] = asyncio.Queue()
    store[message_id] = queue

    async def _produce() -> None:
        # Full conversation streaming including tool events
        client = MCPClient()
        try:
            logger.info(
                "gateway.producer.start",
                extra={
                    "session_id": session_id,
                    "message_id": message_id,
                    "query_preview": (payload.query or "")[:200],
                },
            )
            # Ensure MCP server is connected for tool execution
            server_path = os.getenv(
                "MCP_SERVER_PATH", "google_mcp/google_admin/mcp_server.py"
            )
            logger.info(
                "gateway.producer.connect", extra={"server_path": server_path}
            )
            await client.connect_to_server(server_path)
            async for event in client.stream_conversation(payload.query):
                await queue.put(json.dumps(event))
        except Exception as e:  # pragma: no cover - defensive fallback
            # Fallback to plain token streaming if MCP/tool path fails
            logger.exception("gateway.producer.error")
            await queue.put(json.dumps({"type": "error", "message": str(e)}))
            for token in client.stream_text(payload.query):
                await queue.put(json.dumps({"type": "token", "text": token}))
            await queue.put(json.dumps({"type": "final", "text": ""}))
        finally:
            try:
                await client.cleanup()
            except Exception:
                pass
            await queue.put("__EOF__")
            logger.info(
                "gateway.producer.end",
                extra={"session_id": session_id, "message_id": message_id},
            )

    # Fire-and-forget producer
    asyncio.create_task(_produce())
    return {"message_id": message_id}


@app.get("/gateway/v1/sessions/{session_id}/stream")
async def stream(session_id: str, cursor: str) -> StreamingResponse:
    import asyncio

    store = _ensure_session(session_id)
    queue: asyncio.Queue[str] | None = store.get(cursor)
    if queue is None:
        raise HTTPException(status_code=404, detail="unknown message cursor")

    async def event_source() -> Any:
        while True:
            data = await queue.get()
            if data == "__EOF__":
                yield 'data: {"type": "end"}\n\n'
                break
            yield f"data: {data}\n\n"
            await asyncio.sleep(0)  # cooperative scheduling

    return StreamingResponse(event_source(), media_type="text/event-stream")


# Lambda handler (via Mangum) when running inside AWS Lambda
if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
    # Lazy import to avoid hard dependency outside Lambda runtime
    from mangum import Mangum  # type: ignore

    handler = Mangum(app)
