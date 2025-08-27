"""Completion notifier Lambda.

Updates the original Slack message thread with the final execution result
once the approved action has completed.

Inputs (from Step Functions):
- request_id: The approval request id used to look up metadata in DynamoDB
- result: The full Execute Lambda result object (arbitrary shape)

Behavior:
- Look up the approval item by request_id
- If Slack metadata is present (slack_ts, slack_channel), post a chat.update
  using the Slack bot token to replace the waiting message with the final text
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from typing import Any

import src.slack_blockkit as slack_blockkit
from src.dynamodb_utils import get_approval_table


def _extract_text_from_result(result_obj: Any) -> str:
    """Return a concise string from an arbitrary result object.

    Args:
        result_obj: Arbitrary object coming from Execute Lambda.

    Returns:
        String to post into Slack.
    """
    # Common shapes:
    # - {'statusCode': 200, 'body': '...'}
    # - dict with 'body' or 'result' keys
    try:
        if isinstance(result_obj, dict):
            # If nested under 'body' and is JSON string or object
            body = result_obj.get("body")
            if isinstance(body, dict | list):
                return json.dumps(body)
            if isinstance(body, str):
                return body
            # Fallback to a generic dump
            return json.dumps(result_obj)
        # If the result is a raw string
        if isinstance(result_obj, str):
            return result_obj
        return json.dumps(result_obj)
    except Exception:
        return str(result_obj)


def _chunk_text(text: str, max_len: int) -> Iterable[str]:
    """Yield chunks of text no longer than max_len, on safe boundaries.

    Tries to split on paragraph or line boundaries before falling back to
    hard slicing to respect Slack's 3000-character mrkdwn limit per section.
    """
    start = 0
    length = len(text)
    while start < length:
        end = min(start + max_len, length)
        # Try to split at a nearby newline for nicer chunks
        split_at = text.rfind("\n\n", start, end)
        if split_at == -1:
            split_at = text.rfind("\n", start, end)
        if split_at == -1 or split_at <= start + (max_len // 2):
            split_at = end
        yield text[start:split_at]
        start = split_at


def _build_blocks_from_text(
    text: str, *, request_id: str | None
) -> list[dict[str, Any]]:
    """Craft a Block Kit message from raw or markdown text.

    Structure:
    - Header: "Execution Result"
    - Context: Request ID when available
    - One or more section blocks with mrkdwn text (chunked)
    - If text appears JSON-like, render each section inside ``` fences
    """
    # First, try to parse text as JSON payload from an MCP tool
    try:
        obj = json.loads(text)
    except Exception:
        obj = None

    # If it's a GIF payload or contains explicit blocks, construct the exact
    # structure requested: header, context, a section with text, then image.
    blocks = [{
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Execution Result"
        }},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"*Request ID:* {request_id}"
                }
            ]
        }
    ]
    for line in text.split("\n"):
        if line.startswith("https://"):
            blocks.append({
                "type": "image",
                "image_url": line,
                "alt_text": "GIF"
            })
        else:
            if line.strip():
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": line
                }})

    return  blocks



def lambda_handler(event: dict[str, Any], _: Any) -> dict[str, Any]:
    """Entry point for Lambda proxy from Step Functions.

    Args:
        event: Expected to contain 'request_id' and 'result'.
            Tolerates variations.
    """
    # Resolve execution context
    request_id: str | None = (
        event.get("request_id")
        or event.get("Input", {}).get("request_id")
        or event.get("body", {}).get("request_id")
    )
    result_obj: Any = (
        event.get("result")
        or event.get("execute_result")
        or event.get("body")
        or event
    )

    if not request_id:
        # Nothing to do without a request id; return gracefully
        return {
            "statusCode": 200,
            "body": {"ok": False, "skipped": "missing_request_id"},
        }

    # DynamoDB lookup for Slack metadata
    table = get_approval_table()
    try:
        item = table.get_item(Key={"request_id": request_id}).get("Item") or {}
    except Exception:
        item = {}

    channel_id: str | None = item.get("slack_channel") or item.get(
        "channel_id"
    )
    ts: str | None = item.get("slack_ts") or item.get("ts")

    if not channel_id or not ts:
        # No Slack metadata to update; consider success
        return {
            "statusCode": 200,
            "body": {
                "ok": True,
                "updated": False,
                "reason": "no_slack_metadata",
            },
        }

    # Resolve token
    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not bot_token:
        return {
            "statusCode": 200,
            "body": {"ok": False, "skipped": "no_token"},
        }

    # Build text and blocks from raw/markdown
    text = _extract_text_from_result(result_obj) or "Request completed."

    blocks = _build_blocks_from_text(text, request_id=request_id)

    # Update message via Block Kit client
    slack_blockkit.update_message(channel_id, ts, text=text, blocks=blocks)

    return {"statusCode": 200, "body": {"ok": True, "updated": True}}


if __name__ == "__main__":
    event = {
        "message": "Request has been approved",
        "status": "approved",
        "request_id": "f2ddaf399e521a7778a6662b2060dc227d8cb701e90062eda0fe50715b141c41",
        "execute_result": {
            "statusCode": 200,
            "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
            },
            "body": "Here's a cute cat GIF for you.\n\nEnjoy this adorable feline friend!\n\nhttps://media.tenor.com/0Q5IZ6e9pC8AAAAC/cat-cute-cat.gif\n\n"
        }
    }
    lambda_handler(event, {})
