"""Unified Slack Block Kit client for AgentCore.

All Slack messaging should go through this module using Block Kit. This
eliminates multiple ad-hoc Slack paths (webhooks, scattered helpers) and
centralizes payload construction and posting.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import requests

from src.policy import ApprovalOutcome
from src.constants import REQUEST_ID_LENGTH


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
    text: str = "",
    *,
    token: str | None = None,
    blocks: list[dict[str, Any]] | None = None,
    thread_ts: str | None = None,
) -> bool:
    """Post a Block Kit message to a channel (with optional thread)."""
    payload = {"blocks": blocks} if blocks else {"text": text}
    resp = requests.post(
        os.environ.get("SLACK_WEBHOOK_URL"),
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
        timeout=10,
    )

    return bool(resp.status_code == 200)


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
    payload["as_user"] = True

    data = _slack_api("chat.update", bot_token, payload)

    if not data.get("ok"):
        payload["thread_ts"] = ts
        data = _slack_api("chat.postMessage", bot_token, payload)
    return bool(data.get("ok"))


def build_approval_blocks(
    *,
    title: str,
    request_id: str,
    requester: str,
    proposed_action: str,
    approve_value: str,
    reject_value: str,
    proposed_tool: str,
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
                {"type": "mrkdwn", "text": f"*Request ID:*\n{request_id[:10]}"},
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
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Proposed Tool:*\n{proposed_tool}",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "style": "primary",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "action_id": ApprovalOutcome.ALLOW,
                    "value": approve_value,
                },
                {
                    "type": "button",
                    "style": "danger",
                    "text": {"type": "plain_text", "text": "Reject"},
                    "action_id": ApprovalOutcome.DENY,
                    "value": reject_value,
                },
            ],
        },
    ]


def _to_mrkdwn(md: str) -> str:
    # headers -> bold line
    md = re.sub(r"^\s*#{1,6}\s*(.+)$", r"*\1*", md, flags=re.MULTILINE)
    # bold **x** -> *x*
    # md = re.sub(r'\*\*(.+?)\*\*', r'*\1*', md)
    # italics __x__ -> _x_
    md = re.sub(r"__(.+?)__", r"_\1_", md)
    # images ![alt](url) -> (move to image blocks separately; leave URL)
    md = re.sub(r"!\[[^\]]*\]\(([^)]+)\)", r"\1", md)
    # links [text](url) -> <url|text>
    md = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", md)
    # horizontal rules -> divider sentinel
    md = re.sub(r"^\s*[-*_]{3,}\s*$", r"::DIVIDER::", md, flags=re.MULTILINE)
    return md.strip()


def extract_urls(text: str):
    # Regex to match http, https, and www style URLs
    url_pattern = re.compile(r"http[s]://[a-z|A-Z|0-9|.|/\-]+", re.IGNORECASE)
    return url_pattern.findall(text)


def get_header_and_context(
    request_id: str, title: str
) -> list[dict[str, Any]]:
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": title},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"*Request ID:* `{str(request_id[:REQUEST_ID_LENGTH] or '')}`",
                }
            ],
        },
    ]


def build_blocks_from_text(
    text: str, *, request_id: str | None
) -> tuple[list[dict[str, Any]], int]:
    """Craft Block Kit using mrkdwn sections with chunking and context.

    Structure:
    - Header: "Execution Result"
    - Context: Request ID when available (mrkdwn)
    - One or more section blocks with mrkdwn text (chunked)
    """
    # Header and context
    blocks = get_header_and_context(request_id, "Execution Result")
    char_count = 0
    for img_url in extract_urls(text):
        if img_url.endswith(".gif"):
            blocks.append(
                {"type": "image", "image_url": img_url, "alt_text": img_url}
            )
            return (
                [blocks[i : i + 50] for i in range(0, len(blocks), 50)],
                char_count,
                [img_url],
            )

    for chunk in _to_mrkdwn(text).split("\n\n"):
        blocks.append({"type": "divider"})
        blocks.append({"type": "markdown", "text": chunk})
        char_count += len(chunk)

    return (
        [blocks[i : i + 50] for i in range(0, len(blocks), 50)],
        char_count,
        extract_urls(text),
    )


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
