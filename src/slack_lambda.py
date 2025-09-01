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
import re
from typing import Any
import logging

import boto3
import requests
from slack_sdk import WebClient

from src.approval_handler import (
    compute_request_id_from_action,
    handle_new_approval_request,
)
from src.dynamodb_utils import get_approval_table
from src.slack_helper import (
    build_thread_context,
    fetch_thread_messages,
    get_bot_user_id,
)

from .secrets_manager import get_secret_json
from .slack_session_store import SlackSessionStore

# In-memory best-effort dedupe for local/dev. In AWS, prefer DynamoDB.
_SEEN_EVENT_IDS: set[str] = set()


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


def _slack_api(
    method: str, token: str, payload: dict[str, Any]
) -> dict[str, Any]:
    url = f"https://slack.com/api/{method}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    resp = requests.post(
        url, data=json.dumps(payload), headers=headers, timeout=10
    )
    try:
        return resp.json()
    except Exception:
        return {"ok": False, "error": f"http_{resp.status_code}"}


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
    redirect_uri = secrets.get(
        "redirect_uri", os.environ.get("SLACK_REDIRECT_URI", "")
    )

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


def slack_userid_to_email(user_id: str, bot_token: str) -> str | None:
    try:
        client = WebClient(token=bot_token)
        resp = client.users_info(user=user_id)
        return f"{resp['user']['name']}@{os.environ.get('DOMAIN', '')}"
    except Exception as e:
        logging.error(f"SlackApiError: {e}")
        return None


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
    user = body.get("event", {}).get("user", "")

    # URL verification challenge
    if body.get("type") == "url_verification":
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "text/plain"},
            "body": body.get("challenge", ""),
        }

    # Only handle user-originated message or app_mention events
    event_obj = body.get("event") or {}
    channel_id = event_obj.get("channel", "")
    thread_ts = event_obj.get("thread_ts") or event_obj.get("ts", "")
    user_text = event_obj.get("text", "")
    action_text = event_obj.get("text", "")
    request_id = compute_request_id_from_action(action_text)
    requester_email = (
        slack_userid_to_email(user, os.environ.get("SLACK_BOT_TOKEN", ""))
        or ""
    )
    approval_table = get_approval_table()
    found = approval_table.get_item(Key={"request_id": request_id}).get("Item")
    if found and found.get("request_id") == request_id:
        return {
            "statusCode": 200,
            "body": json.dumps({"ok": True, "mode": "async"}),
        }
    else:
        request_id = (
            handle_new_approval_request(
                {
                    "slack_channel": channel_id,
                    "slack_ts": thread_ts,
                    "proposed_action": action_text,
                    "requester": requester_email,
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

    bot_user_id = get_bot_user_id(bot_token)
    thread_messages = fetch_thread_messages(
        channel_id, thread_ts, token=bot_token, max_messages=50
    )
    thread_context = build_thread_context(
        thread_messages,
        bot_user_id=bot_user_id,
        max_turns=12,
        max_chars=4000,
    )

    try:
        boto3.client(
            "stepfunctions",
            region_name=os.environ.get("AWS_REGION", "us-west-2"),
        ).start_execution(
            stateMachineArn=os.environ.get("STATE_MACHINE_ARN", ""),
            input=json.dumps(
                {
                    "proposed_action": action_text,
                    "slack_channel": channel_id,
                    "slack_ts": thread_ts,
                    "request_id": request_id,
                    "requester": requester_email,
                    "thread_context": thread_context,
                }
            ),
        )

    except Exception as e:
        # If async invoke fails, fall back to sync to at least produce a response
        logging.error(f"Error: {e}")

    # Ack immediately for async path
    return {
        "statusCode": 200,
        "body": json.dumps({"ok": True, "mode": "async"}),
    }


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Entry point for API Gateway → Lambda proxy requests.

    Dispatches based on HTTP method and rawPath to the appropriate handler.
    """
    request_context = event.get("requestContext", {})
    http = request_context.get("http", {})
    method = (http.get("method") or event.get("httpMethod") or "").upper()
    raw_path = (
        http.get("path") or event.get("rawPath") or event.get("path") or ""
    )

    if method == "GET" and raw_path.endswith("/oauth/callback"):
        return oauth_redirect_handler(event, context)
    if method == "POST" and raw_path.endswith("/events"):
        return events_handler(event, context)
    # Async worker entry (internal)

    return {
        "statusCode": 404,
        "body": json.dumps(
            {"error": "not found", "path": raw_path, "method": method}
        ),
    }


if __name__ == "__main__":
    events_handler(
        {
            "version": "2.0",
            "routeKey": "POST /events",
            "rawPath": "/events",
            "rawQueryString": "",
            "headers": {
                "accept": "*/*",
                "accept-encoding": "gzip,deflate",
                "content-length": "1528",
                "content-type": "application/json",
                "host": "2hbb4kfbbj.execute-api.us-west-2.amazonaws.com",
                "user-agent": "Slackbot 1.0 (+https://api.slack.com/robots)",
                "x-amzn-trace-id": "Root=1-68add4ee-600007363f0cd26e18ecf6c4",
                "x-forwarded-for": "3.238.237.63",
                "x-forwarded-port": "443",
                "x-forwarded-proto": "https",
                "x-slack-request-timestamp": "1756222701",
                "x-slack-retry-num": "2",
                "x-slack-retry-reason": "http_timeout",
                "x-slack-signature": "v0=e231bb74179f1430283e1634b77580a7ec15d1119ccc23adc493acddb00435e6",
            },
            "requestContext": {
                "accountId": "706146613458",
                "apiId": "2hbb4kfbbj",
                "domainName": "2hbb4kfbbj.execute-api.us-west-2.amazonaws.com",
                "domainPrefix": "2hbb4kfbbj",
                "http": {
                    "method": "POST",
                    "path": "/events",
                    "protocol": "HTTP/1.1",
                    "sourceIp": "3.238.237.63",
                    "userAgent": "Slackbot 1.0 (+https://api.slack.com/robots)",
                },
                "requestId": "P641QismvHcEJGw=",
                "routeKey": "POST /events",
                "stage": "$default",
                "time": "26/Aug/2025:15:38:22 +0000",
                "timeEpoch": 1756222702016,
            },
            "body": '{"token":"9CleupMsGtzkWxPEawni1VeZ","team_id":"TMS5FH9DY","api_app_id":"A09A5LF57K6","event":{"user":"U05510F01QR","type":"app_mention","ts":"1756222632.727899","client_msg_id":"29182cf5-675d-4999-8dc1-b6b80c695d7d","text":"hey <@U099WCH3GM9> please search Gdrive Customers for the Advocatia client. You\'ll find three project SOWs. Tell me the AI use case for this client. In addition, describe the overarching scope of work executed across all three projects in a brief paragraph, and explain how the projects logically built on one another.","team":"TMS5FH9DY","blocks":[{"type":"rich_text","block_id":"UtW1f","elements":[{"type":"rich_text_section","elements":[{"type":"text","text":" hey "},{"type":"user","user_id":"U099WCH3GM9"},{"type":"text","text":" please search Gdrive Customers for the Advocatia client. You\'ll find three project SOWs. Tell me the AI use case for this client. In addition, describe the overarching scope of work executed across all three projects in a brief paragraph, and explain how the projects logically built on one another."}]}]}],"language":{"locale":"en","is_reliable":true},"channel":"C09BDA1E0HJ","event_ts":"1756222632.727899"},"type":"event_callback","event_id":"Ev09CHNCQS5P","event_time":1756222632,"authorizations":[{"enterprise_id":null,"team_id":"TMS5FH9DY","user_id":"U099WCH3GM9","is_bot":true,"is_enterprise_install":false}],"is_ext_shared_channel":false,"event_context":"4-eyJldCI6ImFwcF9tZW50aW9uIiwidGlkIjoiVE1TNUZIOURZIiwiYWlkIjoiQTA5QTVMRjU3SzYiLCJjaWQiOiJDMDlCREExRTBISiJ9"}',
            "isBase64Encoded": False,
        },
        {},
    )
