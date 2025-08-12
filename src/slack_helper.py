"""Slack integration helper utilities.

This module centralizes Slack-related functionality so that other modules
can remain agnostic of Slack specifics. It currently supports posting
simple webhook messages. A future iteration will add Block Kit interactive
messages and an interactivity endpoint.

Design goals:
- Keep a small, testable surface area
- Avoid importing application modules to prevent circular dependencies

Usage:
- Use `post_slack_webhook_message` to send a basic text message to Slack.
- Provide an optional `function_url_getter` to resolve approval action links
  (kept optional to avoid hard coupling and enable easy testing).
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, Optional, Tuple

import requests
import hashlib
import hmac
import time
import json as _json
from urllib.parse import quote_plus


def _build_slack_text(
    content: Dict[str, str],
    function_url_getter: Optional[Callable[[], str]] = None,
) -> str:
    """Build the Slack message text for a webhook post.

    Args:
        content: Message content assembled by the caller. Expected keys include
            'title', 'request_id', 'status', 'requester', optional 'approver',
            'agent_prompt', 'proposed_action', and optional 'reason'.
        function_url_getter: Optional callable that returns an approval action
            base URL. When provided and status is "pending", approval links will
            be included.

    Returns:
        The formatted text string for Slack.
    """
    lines: list[str] = [
        f"*{content.get('title', 'AgentCore Notification')}*",
        f"*Request ID*: {content.get('request_id', '')}",
        f"*Status*: {content.get('status', '')}",
        f"*Requester*: {content.get('requester', '')}",
    ]

    approver = content.get("approver")
    if approver:
        lines.append(f"*Approver*: {approver}")

    lines.extend(
        [
            "",
            "*Agent Prompt:*",
            content.get("agent_prompt", ""),
            "",
            "*Proposed Action:*",
            content.get("proposed_action", ""),
        ]
    )

    reason = content.get("reason")
    if reason:
        lines.extend(["", "*Reason:*", reason])

    # Append approval links for pending status if a function URL resolver is provided
    if content.get("status") == "pending" and function_url_getter is not None:
        try:
            function_url = function_url_getter() or ""
        except Exception:
            function_url = ""
        if function_url:
            request_id = content.get("request_id", "")
            approve_link = f"{function_url}?request_id={request_id}&action=approve"
            reject_link = f"{function_url}?request_id={request_id}&action=reject"
            lines.extend(
                [
                    "",
                    "*Approval Actions:*",
                    f"Approve:{approve_link}|",
                    f"Reject: {reject_link}|",
                ]
            )

    return "\n".join(lines)


def post_slack_webhook_message(
    content: Dict[str, str],
    *,
    function_url_getter: Optional[Callable[[], str]] = None,
    timeout_seconds: int = 5,
) -> bool:
    """Post a message to Slack via Incoming Webhook.

    Args:
        content: Structured content used to build the message text.
        function_url_getter: Optional callable to resolve approval links. If provided
            and `content['status'] == 'pending'`, links will be appended.
        timeout_seconds: HTTP request timeout in seconds.

    Returns:
        True if Slack accepted the message, False otherwise or when webhook is not configured.
    """
    webhook_url: Optional[str] = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return False

    text: str = _build_slack_text(content, function_url_getter=function_url_getter)
    payload: Dict[str, Any] = {"text": text}

    response = requests.post(webhook_url, json=payload, timeout=timeout_seconds)
    return response.status_code == 200 and response.text.strip().lower() in {"ok", ""}


__all__ = [
    "post_slack_webhook_message",
    "build_block_approval_message",
    "post_slack_block_approval",
    "verify_slack_request",
    "parse_action_from_interaction",
    "respond_via_response_url",
]


def build_block_approval_message(content: Dict[str, str], channel_id: str) -> Dict[str, Any]:
    """Build a Block Kit message with Approve/Reject buttons.

    Args:
        content: Structured message content with keys like 'title', 'request_id',
            'requester', 'proposed_action', 'reason', and 'status'.
        channel_id: Slack channel ID to post into.

    Returns:
        Chat.postMessage JSON payload including blocks.
    """
    title = content.get("title", "AgentCore Approval")
    request_id = content.get("request_id", "")
    requester = content.get("requester", "")
    proposed_action = content.get("proposed_action", "")

    approve_value = _json.dumps({"request_id": request_id, "action": "approve"}, separators=(",", ":"))
    reject_value = _json.dumps({"request_id": request_id, "action": "reject"}, separators=(",", ":"))

    blocks: list[Dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": title, "emoji": True}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Request ID:*\n{request_id}"},
                {"type": "mrkdwn", "text": f"*Requester:*\n{requester}"},
            ],
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Proposed Action:*\n{proposed_action}"}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "style": "primary",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "action_id": "approve",
                    "value": approve_value,
                },
                {
                    "type": "button",
                    "style": "danger",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "action_id": "reject",
                    "value": reject_value,
                },
            ],
        },
    ]

    payload: Dict[str, Any] = {
        "channel": channel_id,
        "text": title,
        "unfurl_links": False,
        "unfurl_media": False,
        "blocks": blocks,
    }
    return payload


def post_slack_block_approval(
    content: Dict[str, str],
    *,
    channel_id: str,
    bot_token: Optional[str] = None,
    timeout_seconds: int = 5,
) -> bool:
    """Post a Block Kit approval message with interactive buttons.

    Args:
        content: Structured message content.
        channel_id: Slack channel to post in.
        bot_token: Slack bot token; if None, will read SLACK_BOT_TOKEN from env.
        timeout_seconds: HTTP timeout.

    Returns:
        True on success; False otherwise.
    """
    token = bot_token or os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        return False

    payload = build_block_approval_message(content, channel_id=channel_id)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    resp = requests.post("https://slack.com/api/chat.postMessage", data=_json.dumps(payload), headers=headers, timeout=timeout_seconds)
    try:
        data = resp.json()
    except Exception:
        data = {"ok": False}
    return resp.status_code == 200 and bool(data.get("ok"))


def verify_slack_request(signing_secret: str, timestamp: str, raw_body: bytes, signature: str, *, tolerance: int = 60 * 5) -> bool:
    """Verify Slack signing signature for interactivity requests.

    Args:
        signing_secret: Slack signing secret.
        timestamp: X-Slack-Request-Timestamp header value.
        raw_body: Raw HTTP request body bytes.
        signature: X-Slack-Signature header value.
        tolerance: Allowed clock skew in seconds.

    Returns:
        True if signature is valid; False otherwise.
    """
    if not signing_secret or not timestamp or not signature:
        return False

    try:
        ts = int(timestamp)
    except Exception:
        return False

    if abs(int(time.time()) - ts) > tolerance:
        return False

    basestring = f"v0:{timestamp}:{raw_body.decode('utf-8')}".encode("utf-8")
    digest = hmac.new(signing_secret.encode("utf-8"), basestring, hashlib.sha256).hexdigest()
    expected = f"v0={digest}"
    # Constant-time compare
    if not hmac.compare_digest(expected, signature):
        return False
    return True


def parse_action_from_interaction(payload: Dict[str, Any]) -> Tuple[str, str, str]:
    """Extract (request_id, action, user_id) from Slack interaction payload.

    Raises ValueError if required fields are missing.
    """
    if payload.get("type") != "block_actions":
        raise ValueError("Unsupported interaction type")
    actions = payload.get("actions") or []
    if not actions:
        raise ValueError("No actions in payload")
    first = actions[0]
    action = first.get("action_id") or ""
    value = first.get("value") or ""
    try:
        parsed = _json.loads(value) if value else {}
    except Exception:
        parsed = {}
    request_id = parsed.get("request_id") or payload.get("container", {}).get("message_ts") or ""
    action = parsed.get("action") or action
    if action not in {"approve", "reject"}:
        raise ValueError("Unknown action")
    user_id = (payload.get("user") or {}).get("id") or ""
    if not request_id or not user_id:
        raise ValueError("Missing request_id or user_id")
    return request_id, action, user_id


def respond_via_response_url(response_url: str, text: str, *, timeout_seconds: int = 5) -> bool:
    """Update Slack message via response_url, replacing original blocks with text."""
    if not response_url:
        return False
    payload = {"replace_original": True, "text": text}
    resp = requests.post(response_url, json=payload, timeout=timeout_seconds)
    return 200 <= resp.status_code < 300


