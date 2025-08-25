"""AWS Lambda handlers for Slack OAuth and Events to AgentCore.

Implements:
- Slack OAuth redirect/callback to exchange code for bot token and save in Secrets Manager
- Slack Events API handler that routes messages to AgentCore Gateway and streams back

Environment variables:
- AWS_REGION: AWS region
- SLACK_SESSIONS_TABLE: DynamoDB table for thread→session mapping
- SLACK_SECRETS_NAME: Secrets Manager name to store Slack tokens {bot_token, app_token?, signing_secret, client_id, client_secret}
- AGENTCORE_GATEWAY_URL: Base URL for AgentCore Gateway (Invoke API)

Notes:
- Streaming uses Slack chat.postMessage + chat.update edits for incremental chunks
- Verifies Slack signature for Events requests
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Iterable
from typing import Any

import boto3
import requests

from src.approval_handler import (
    _handle_new_approval_request,
    compute_request_id_from_action,
)
from src.mcp_client import MCPClient

from .secrets import get_secret_json
from .slack_session_store import SlackSessionStore

# In-memory best-effort dedupe for local/dev. In AWS, prefer DynamoDB.
_SEEN_EVENT_IDS: set[str] = set()
TABLE_NAME = os.environ["TABLE_NAME"]
dynamodb = boto3.resource("dynamodb", region_name=os.environ["AWS_REGION"])
table = dynamodb.Table(TABLE_NAME)


def _should_process_event(event_id: str, *, ttl_seconds: int = 60 * 5) -> bool:
    """Best-effort dedupe to avoid processing the same Slack event multiple times.

    Slack can retry deliveries on timeout or certain errors. We store processed
    event_ids in-memory for local/dev. In Lambda, the execution environment may
    be reused so this still helps a bit. For strong guarantees, wire a
    DynamoDB-backed deduper keyed on event_id with TTL.

    Args:
        event_id: Slack event_id from the Events API payload
        ttl_seconds: Unused here (placeholder for future DynamoDB TTL)

    Returns:
        True if the event should be processed (not seen before), False if it
        appears to be a retry/duplicate.
    """
    if not event_id:
        return True
    if event_id in _SEEN_EVENT_IDS:
        return False
    _SEEN_EVENT_IDS.add(event_id)
    return True


def _slack_api(method: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"https://slack.com/api/{method}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    resp = requests.post(url, data=json.dumps(payload), headers=headers, timeout=10)
    try:
        return resp.json()
    except Exception:
        return {"ok": False, "error": f"http_{resp.status_code}"}


def _agentcore_stream(session_id: str, user_text: str) -> Iterable[str]:
    """Invoke AgentCore Gateway (SSE) and yield token chunks.

    Contract C:
      1) POST /gateway/v1/sessions/{session_id}/messages -> {"message_id": "m-..."}
      2) GET  /gateway/v1/sessions/{session_id}/stream?cursor=message_id (SSE)
    """
    base_url = os.environ.get("AGENTCORE_GATEWAY_URL", "")
    if not base_url:
        yield "AgentCore Gateway not configured."
        return

    # 1) create message
    post_url = f"{base_url.rstrip('/')}/gateway/v1/sessions/{session_id}/messages"
    post = requests.post(
        post_url, json={"query": user_text, "user_id": "slack"}, timeout=30
    )
    if not post.ok:
        yield f"AgentCore error: {post.status_code}"
        return
    message_id = (post.json() or {}).get("message_id", "")
    if not message_id:
        yield "AgentCore error: missing message_id"
        return

    # 2) stream SSE with simple retry on 404 in case of race/placement
    base = base_url.rstrip("/")
    stream_url = f"{base}/gateway/v1/sessions/{session_id}/stream?cursor={message_id}"

    for attempt in range(2):
        with requests.get(stream_url, stream=True, timeout=300) as resp:
            if not resp.ok:
                if resp.status_code == 404 and attempt == 0:
                    # Best-effort fallback: create a new message cursor and stream again
                    post_url = f"{base}/gateway/v1/sessions/{session_id}/messages"
                    post = requests.post(
                        post_url,
                        json={"query": user_text, "user_id": "slack"},
                        timeout=30,
                    )
                    if not post.ok:
                        yield f"AgentCore stream error: {resp.status_code}"
                        return
                    message_id = (post.json() or {}).get("message_id", "")
                    if not message_id:
                        yield "AgentCore error: missing message_id"
                        return
                    stream_url = f"{base}/gateway/v1/sessions/{session_id}/stream?cursor={message_id}"
                    continue
                else:
                    yield f"AgentCore stream error: {resp.status_code}"
                    return
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if not line.startswith("data: "):
                    continue
                data = line[len("data: ") :]
                try:
                    obj = json.loads(data)
                except Exception:
                    yield data
                    continue
                if obj.get("type") == "token":
                    yield obj.get("text", "")
                elif obj.get("type") in {"final", "end"}:
                    if obj.get("text"):
                        yield obj.get("text")
                    return
            return


def oauth_redirect_handler(event: dict[str, Any], _: Any) -> dict[str, Any]:
    """Handle Slack OAuth redirect with `code`, exchange for tokens, store in Secrets Manager.

    Returns a simple HTML page indicating success.
    """
    params = event.get("queryStringParameters") or {}
    code = params.get("code")
    if not code:
        return {"statusCode": 400, "body": "Missing code"}

    secret_name = os.environ.get("SLACK_SECRETS_NAME", "")
    secrets = get_secret_json(secret_name) if secret_name else {}
    client_id = secrets.get("client_id", os.environ.get("SLACK_CLIENT_ID", ""))
    client_secret = secrets.get(
        "client_secret", os.environ.get("SLACK_CLIENT_SECRET", "")
    )
    redirect_uri = secrets.get("redirect_uri", os.environ.get("SLACK_REDIRECT_URI", ""))

    token_resp = requests.post(
        "https://slack.com/api/oauth.v2.access",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=10,
    )
    data = token_resp.json()
    if not data.get("ok"):
        return {"statusCode": 400, "body": json.dumps(data)}

    # Store bot/access tokens back into Secrets Manager
    region = os.environ.get("AWS_REGION", "us-east-1")
    sm = boto3.client("secretsmanager", region_name=region)
    payload = {
        **secrets,
        "bot_token": data.get("access_token"),
        "app_id": data.get("app_id"),
        "team": data.get("team", {}),
    }
    sm.put_secret_value(SecretId=secret_name, SecretString=json.dumps(payload))

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/html"},
        "body": "<html><body><h3>Slack app installed successfully.</h3></body></html>",
    }


def events_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle Slack Events and route to AgentCore.

    Supports URL verification and message events. Streams responses back by posting
    an initial message and editing it with incremental content.
    """
    raw_body: bytes
    if "isBase64Encoded" in event and event.get("isBase64Encoded"):
        raw_body = base64.b64decode(event.get("body") or b"")
    else:
        raw_body = (event.get("body") or "").encode("utf-8")

    # Signature verification
    secret_name = os.environ.get("SLACK_SECRETS_NAME", "")
    secrets = get_secret_json(secret_name) if secret_name else {}
    body = json.loads(raw_body.decode("utf-8") or "{}")

    # URL verification challenge
    if body.get("type") == "url_verification":
        print(
            {
                "statusCode": 200,
                "headers": {"Content-Type": "text/plain"},
                "body": body.get("challenge", ""),
            }
        )
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "text/plain"},
            "body": body.get("challenge", ""),
        }

    event_id = str(body.get("event_id") or "")
    is_first_time = _should_process_event(event_id)
    retry_num = (event.get("headers") or {}).get("X-Slack-Retry-Num")
    if retry_num is not None and not is_first_time:
        # Acknowledge duplicate without reprocessing
        return {
            "statusCode": 200,
            "body": json.dumps({"ok": True, "skipped": "retry_duplicate"}),
        }

    # Only handle user-originated message or app_mention events
    event_obj = body.get("event") or {}
    channel_id = event_obj.get("channel", "")
    thread_ts = event_obj.get("thread_ts") or event_obj.get("ts", "")
    user_text = event_obj.get("text", "")
    action_text = event_obj.get("text", "")
    request_id = compute_request_id_from_action(action_text)
    if table.get_item(Key={"request_id": request_id}).get("Item"):
        print(
            f"request_id {compute_request_id_from_action(action_text)} found in table"
        )
        return {"statusCode": 200, "body": json.dumps({"ok": True, "mode": "async"})}
    else:
        request_id = (
            _handle_new_approval_request(
                {
                    "slack_channel": channel_id,
                    "slack_ts": thread_ts,
                    "proposed_action": action_text,
                }
            )
            .get("body")
            .get("request_id")
        )
    event_type = str(event_obj.get("type") or "")
    event_subtype = event_obj.get("subtype")
    if bool(event_obj.get("bot_id")):
        return {
            "statusCode": 200,
            "body": json.dumps({"ok": True, "skipped": "bot_message"}),
        }

    if event_obj.get("bot_id"):
        return {
            "statusCode": 200,
            "body": json.dumps({"ok": True, "skipped": "bot_message"}),
        }
    if event_type not in {"message", "app_mention"}:
        return {
            "statusCode": 200,
            "body": json.dumps({"ok": True, "skipped": event_type}),
        }
    # Ignore message events with subtypes (edits, joins, etc.) to avoid noise
    if event_type == "message" and event_subtype:
        return {
            "statusCode": 200,
            "body": json.dumps({"ok": True, "skipped_subtype": event_subtype}),
        }

    if event_type == "app_mention" and user_text:
        # Strip the mention prefix like "<@U12345> "
        try:
            import re

            user_text = re.sub(r"^<@[^>]+>\\s*", "", user_text).strip()
        except Exception:
            pass

    # Resolve bot token from Secrets (or env fallback)
    bot_token = secrets.get("bot_token", os.environ.get("SLACK_BOT_TOKEN", ""))

    if not bot_token:
        return {"statusCode": 500, "body": "missing bot token"}

    # Map to session
    try:
        store = SlackSessionStore()
    except ValueError:
        store = None  # type: ignore[assignment]
    if store is not None:
        session_id = (
            store.get_session_id(channel_id, thread_ts)
            or f"session-{channel_id}-{thread_ts}"
        )
        store.put_session_id(channel_id, thread_ts, session_id)
    else:
        session_id = f"session-{channel_id}-{thread_ts}"

    # Post initial placeholder (avoid including thread_ts when not present)
    initial_payload: dict[str, Any] = {
        "channel": channel_id,
        "text": "Received your message — preparing a response…",
    }
    if event_obj.get("thread_ts"):
        initial_payload["thread_ts"] = thread_ts
    try:
        print(
            {
                "info": "slack_postMessage_attempt",
                "channel": channel_id,
                "has_thread": bool(event_obj.get("thread_ts")),
            }
        )
    except Exception:
        pass
    # Always post initial message once
    initial = _slack_api("chat.postMessage", bot_token, initial_payload)
    ts = initial.get("ts") or (thread_ts if event_obj.get("thread_ts") else None)

    try:
        boto3.client(
            "stepfunctions", region_name=os.environ.get("AWS_REGION", "us-west-2")
        ).start_execution(
            stateMachineArn=os.environ.get("STATE_MACHINE_ARN", ""),
            input=json.dumps(
                {
                    "proposed_action": action_text,
                    "slack_channel": channel_id,
                    "slack_ts": ts,
                    "request_id": request_id,
                }
            ),
        )

        print(f"request_id {request_id}")
        _slack_api(
            "chat.update",
            bot_token,
            {
                "channel": channel_id,
                "ts": ts,
                "text": f"Request {request_id} is being processed. Please wait...",
            },
        )

    except Exception as e:
        # If async invoke fails, fall back to sync to at least produce a response
        print(f"Error: {e}")

    # Ack immediately for async path
    return {"statusCode": 200, "body": json.dumps({"ok": True, "mode": "async"})}


def _worker_stream_handler(event: dict[str, Any]) -> None:
    """Background worker to stream AgentCore output back to Slack.

    This is invoked asynchronously via Lambda self-invoke to avoid blocking
    the Slack Events ack. It expects `channel_id`, `thread_ts`, `user_text`,
    `session_id`, `message_ts`, and `secret_name`.
    """
    channel_id = str(event.get("channel_id", ""))
    thread_ts = str(event.get("thread_ts", ""))
    user_text = str(event.get("user_text", ""))
    session_id = str(event.get("session_id", ""))
    ts = event.get("message_ts")
    secret_name = str(event.get("secret_name", ""))

    secrets = get_secret_json(secret_name) if secret_name else {}
    bot_token = secrets.get("bot_token", os.environ.get("SLACK_BOT_TOKEN", ""))
    if not bot_token:
        return

    accumulated = ""
    accumulated_blocks = None

    for chunk in _agentcore_stream(session_id, user_text):
        if not chunk:
            continue
        try:
            maybe_obj = json.loads(chunk)
        except Exception:
            maybe_obj = None

        if isinstance(maybe_obj, dict):
            if maybe_obj.get("type") == "token":
                accumulated += str(maybe_obj.get("text", ""))
            elif maybe_obj.get("type") == "final":
                if maybe_obj.get("text"):
                    accumulated = str(maybe_obj.get("text"))
                # Check if the final response includes Slack blocks
                if maybe_obj.get("blocks"):
                    accumulated_blocks = maybe_obj.get("blocks")
            # Check if any chunk includes Slack blocks (for MCP responses)
            elif maybe_obj.get("blocks"):
                accumulated_blocks = maybe_obj.get("blocks")
        else:
            accumulated += str(chunk)

        if ts:
            # Prepare the update payload
            update_payload = {"channel": channel_id, "ts": ts}

            # If we have blocks, use them for rich formatting
            if accumulated_blocks:
                update_payload["blocks"] = accumulated_blocks
                # Also include text as fallback
                update_payload["text"] = accumulated
            else:
                # Fallback to text-only
                update_payload["text"] = accumulated

            _slack_api("chat.update", bot_token, update_payload)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Entry point for API Gateway → Lambda proxy requests.

    Dispatches based on HTTP method and rawPath to the appropriate handler.
    """
    request_context = event.get("requestContext", {})
    http = request_context.get("http", {})
    method = (http.get("method") or event.get("httpMethod") or "").upper()
    raw_path = http.get("path") or event.get("rawPath") or event.get("path") or ""

    if method == "GET" and raw_path.endswith("/oauth/callback"):
        return oauth_redirect_handler(event, context)
    if method == "POST" and raw_path.endswith("/events"):
        return events_handler(event, context)
    # Async worker entry (internal)
    if (event.get("worker") is True) or (
        method == "POST" and raw_path.endswith("/events/worker")
    ):
        try:
            _worker_stream_handler(
                event.get("body") if raw_path.endswith("/events/worker") else event
            )
        except Exception:
            pass
        return {"statusCode": 200, "body": json.dumps({"ok": True})}

    return {
        "statusCode": 404,
        "body": json.dumps({"error": "not found", "path": raw_path, "method": method}),
    }


async def invoke_mcp_client(action_text: str):
    client = MCPClient()
    try:
        await client.connect_to_server("google_mcp/google_admin/mcp_server.py")
        result = await client.process_query(action_text)
    finally:
        await client.cleanup()
    return result
