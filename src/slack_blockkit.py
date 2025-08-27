"""Unified Slack Block Kit client for AgentCore.

All Slack messaging should go through this module using Block Kit. This
eliminates multiple ad-hoc Slack paths (webhooks, scattered helpers) and
centralizes payload construction and posting.
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests


def _slack_api(
    method: str, token: str, payload: dict[str, Any], *, timeout: int = 10
) -> dict[str, Any]:
    """Low-level Slack Web API POST wrapper.

    Args:
        method: Slack API method path, e.g. "chat.postMessage"
        token: Bot token
        payload: JSON-serializable payload
        timeout: HTTP timeout seconds
    """
    url = f"https://slack.com/api/{method}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    resp = requests.post(
        url, data=json.dumps(payload), headers=headers, timeout=timeout
    )
    try:
        return resp.json()
    except Exception:
        return {"ok": False, "error": f"http_{resp.status_code}"}


def post_message_with_response(
    channel: str,
    text: str,
    *,
    token: str | None = None,
    blocks: list[dict[str, Any]] | None = None,
    thread_ts: str | None = None,
) -> dict[str, Any]:
    """Post a Block Kit message and return the raw Slack API response dict."""
    bot_token = token or os.environ.get("SLACK_BOT_TOKEN", "")
    if not bot_token:
        return {"ok": False, "error": "missing_token"}
    # If blocks not provided, attempt to parse text as JSON (e.g., MCP tool output)
    if blocks is None:
        parsed_text, parsed_blocks = _extract_blocks_from_text_payload(text)
        if parsed_blocks:
            text = parsed_text
            blocks = parsed_blocks
    payload: dict[str, Any] = {"channel": channel, "text": text}
    if blocks:
        payload["blocks"] = blocks
    if thread_ts:
        payload["thread_ts"] = thread_ts
    return _slack_api("chat.postMessage", bot_token, payload)


def post_message(
    channel: str,
    text: str,
    *,
    token: str | None = None,
    blocks: list[dict[str, Any]] | None = None,
    thread_ts: str | None = None,
) -> bool:
    """Post a Block Kit message to a channel (with optional thread)."""
    data = post_message_with_response(
        channel, text, token=token, blocks=blocks, thread_ts=thread_ts
    )
    return bool(data.get("ok"))


def update_message(
    channel: str,
    ts: str,
    *,
    text: str | None = None,
    blocks: list[dict[str, Any]] | None = None,
    token: str | None = None,
) -> bool:
    """Update an existing message via chat.update."""
    bot_token = token or os.environ.get("SLACK_BOT_TOKEN", "")
    if not bot_token:
        return False
    # Auto-extract blocks from JSON text payloads if not provided
    if blocks is None and text is not None:
        new_text, parsed_blocks = _extract_blocks_from_text_payload(text)
        if parsed_blocks:
            text = new_text
            blocks = parsed_blocks
    payload: dict[str, Any] = {"channel": channel, "ts": ts}
    if text is not None:
        payload["text"] = text
    if blocks is not None:
        payload["blocks"] = blocks
    data = _slack_api("chat.update", bot_token, payload)
    return bool(data.get("ok"))


def build_approval_blocks(
    *,
    title: str,
    request_id: str,
    requester: str,
    proposed_action: str,
    approve_value: str,
    reject_value: str,
) -> list[dict[str, Any]]:
    """Compose a standard approval message with Approve/Reject buttons."""
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": title, "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Request ID:*\n{request_id}"},
                {"type": "mrkdwn", "text": f"*Requester:*\n{requester}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Proposed Action:*\n{proposed_action}",
            },
        },
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


def build_blocks_from_text(
    text: str,
    *,
    header: str | None = None,
    context_kv: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Create blocks from plain or markdown text with optional header/context."""
    # If text is a JSON string containing a 'blocks' or 'gif_url', prefer rich blocks
    parsed_text, parsed_blocks = _extract_blocks_from_text_payload(text)
    if parsed_blocks:
        return parsed_blocks
    blocks: list[dict[str, Any]] = []
    if header:
        blocks.append(
            {"type": "header", "text": {"type": "plain_text", "text": header}}
        )
    if context_kv:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"*{k}:* {v}"}
                    for k, v in context_kv.items()
                ],
            }
        )
    blocks.append(
        {"type": "section", "text": {"type": "mrkdwn", "text": text}}
    )
    return blocks


def _extract_blocks_from_text_payload(
    text: str,
) -> tuple[str, list[dict[str, Any]] | None]:
    """Extract Slack blocks from a JSON string payload when possible.

    Accepts text that may be a JSON-serialized object from MCP tools, e.g.
    '{"text":"...","gif_url":"https://...","blocks":[...]}'. If
    'blocks' exist, they are returned. If no 'blocks' but a 'gif_url' exists,
    constructs a simple section + image block set.

    Returns:
        (text, blocks_or_none): the message text to use and any blocks found.
    """
    try:
        obj = json.loads(text)
        if not isinstance(obj, dict):
            return text, None
    except Exception:
        return text, None

    # Prefer explicit blocks when present
    blocks = obj.get("blocks")
    if isinstance(blocks, list) and blocks:
        # Use provided text if available
        new_text = str(obj.get("text") or text)
        return new_text, blocks  # type: ignore[return-value]

    # Otherwise build blocks if a gif_url is present
    gif_url = obj.get("gif_url") or obj.get("image_url")
    if isinstance(gif_url, str) and gif_url:
        new_text = str(obj.get("text") or text)
        alt = str(obj.get("gif_title") or obj.get("alt_text") or "")
        title_text = str(obj.get("gif_title") or "")
        built_blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": new_text}},
            {
                "type": "image",
                "image_url": gif_url,
                "alt_text": alt,
                "title": {"type": "plain_text", "text": title_text},
            },
        ]
        return new_text, built_blocks

    return text, None


__all__ = [
    "post_message",
    "post_message_with_response",
    "update_message",
    "build_approval_blocks",
    "build_blocks_from_text",
]
