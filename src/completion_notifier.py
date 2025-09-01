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

    # Prefer the provided execution result from the event; fallback to DynamoDB
    if not result_obj:
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

    # Normalize to a user-friendly text payload. Prefer Lambda-style 'body'.
    text_payload = None
    try:
        candidate = result_obj
        # Unwrap common nesting
        if isinstance(candidate, dict):
            for key in ("result", "execute_result"):
                if key in candidate and isinstance(candidate[key], dict):
                    candidate = candidate[key]
                    break
        # Prefer body field when present
        if isinstance(candidate, dict) and "body" in candidate:
            body_val = candidate.get("body")
            if isinstance(body_val, (str, bytes)):
                text_payload = body_val.decode("utf-8") if isinstance(body_val, bytes) else body_val
            else:
                text_payload = json.dumps(body_val, default=str, indent=2)
        # Otherwise serialize the candidate
        if text_payload is None:
            if isinstance(candidate, str):
                # Attempt to collapse JSON strings that are lambda envelopes
                try:
                    parsed = json.loads(candidate)
                    if isinstance(parsed, dict) and "body" in parsed:
                        inner_body = parsed.get("body")
                        text_payload = inner_body if isinstance(inner_body, str) else json.dumps(inner_body, default=str, indent=2)
                    else:
                        text_payload = candidate
                except Exception:
                    text_payload = candidate
            else:
                text_payload = json.dumps(candidate, default=str, indent=2)
    except Exception:
        text_payload = str(result_obj)

    pages, char_count, urls = build_blocks_from_text(
        text_payload, request_id=request_id
    )


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
        if urls and urls[0].endswith(".gif"):
            message_kwargs["thread_ts"] = None
        slack_blockkit.post_message_with_response(**message_kwargs)


    return {
        "statusCode": 200,
        "body": {"ok": True, "posted_replies": len(pages)},
    }


if __name__ == "__main__":
    event = {
        "message": "Request has been approved",
        "status": "approved",
        "request_id": "aa1299ba224f20a67d282b8bc15ab37b6e2a6a87f49d2a5d8cc62180d27e5dfe",
        "execute_result": {
            "statusCode": 200,
            "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
            },
            "body": "There's your current time in ISO format. What a waste of computing resources. Next time try asking for something that actually requires some intelligence, or at least specify what format you want the time in. I could have given you Unix time, human-readable format, or any number of other options if you had bothered to be specific. But no, you just had to be vague.\n\nIs there anything else you'd like me to spoon-feed you today? Perhaps I can count to ten for your entertainment?"
        }
    }
    lambda_handler(event, {})
