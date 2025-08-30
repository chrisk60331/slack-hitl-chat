"""Completion notifier Lambda.

Posts the final execution result as threaded replies in Slack once the
approved action has completed. This implementation does not update the
original message; it always posts replies in the same thread to avoid
any Slack rendering quirks with ordered lists or rich text blocks.

Inputs (from Step Functions):
- request_id: The approval request id used to look up metadata in DynamoDB
- result: The full Execute Lambda result object (arbitrary shape)

Behavior:
- Look up the approval item by request_id
- If Slack metadata is present (slack_ts, slack_channel), post one or more
  chat.postMessage calls using ``thread_ts`` to reply in-thread. Long outputs
  are paginated; all pages are replies.
"""

from __future__ import annotations

import json
import os
from typing import Any

import src.slack_blockkit as slack_blockkit
from src.dynamodb_utils import get_approval_table
from src.slack_blockkit import build_blocks_from_text


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
    result_obj = item.get("completion_message")

    if not channel_id or not ts:
        # No Slack metadata to update; consider success
        return {
            "statusCode": 200,
            "body": {
                "ok": True,
                "updated": False,
                "reason": "no_slack_metadata",
                "request_id": request_id,
            },
        }

    # Resolve token
    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not bot_token:
        return {
            "statusCode": 200,
            "body": {"ok": False, "skipped": "no_token"},
        }

    pages, char_count, urls = build_blocks_from_text(
        result_obj, request_id=request_id
    )
    print(f"blocks: {json.dumps(pages, indent=4)}")

    # Post each page as a threaded reply
    total_pages = len(pages)
    for idx, page_blocks in enumerate(pages, start=1):
        suffix = "" if total_pages == 1 else f" ({idx}/{total_pages})"
        cont_text = f"Execution Result{suffix}"
        message_kwargs = {
            "channel": channel_id,
            "text": cont_text,
            "blocks": page_blocks,
            "thread_ts": ts,
        }
        if urls and not urls[0].endswith(".gif"):
            message_kwargs["thread_ts"] = None
        slack_blockkit.post_message_with_response(**message_kwargs)

    print(f"char_count: {char_count}")
    return {
        "statusCode": 200,
        "body": {"ok": True, "posted_replies": len(pages)},
    }


if __name__ == "__main__":
    event = {
        "message": "Request has been approved",
        "status": "approved",
        "request_id": "636c23289f6159a696adc982a2d8c52387fae5cec28b742e2d996840da779806",
    }
    print(lambda_handler(event, {}))
