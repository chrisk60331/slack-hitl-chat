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
from typing import Any

import boto3


def _extract_text_from_result(result_obj: Any) -> str:
    """Return a concise string from an arbitrary result object.

    Args:
        result_obj: Arbitrary object coming from Execute Lambda.

    Returns:
        String to post into Slack.
    """
    # Common shapes: {'statusCode': 200, 'body': '...'} or dict with body/result
    try:
        if isinstance(result_obj, dict):
            # If nested under 'body' and is JSON string or object
            body = result_obj.get("body")
            if isinstance(body, (dict, list)):
                return json.dumps(body)[:3000]
            if isinstance(body, str):
                return body[:3000]
            # Fallback to a generic dump
            return json.dumps(result_obj)[:3000]
        # If the result is a raw string
        if isinstance(result_obj, str):
            return result_obj[:3000]
        return json.dumps(result_obj)[:3000]
    except Exception:
        return str(result_obj)[:3000]


def lambda_handler(event: dict[str, Any], _: Any) -> dict[str, Any]:
    """Entry point for Lambda proxy from Step Functions.

    Args:
        event: Expected to contain 'request_id' and 'result'. Tolerates variations.
    """
    # Resolve execution context
    request_id: str | None = (
        event.get("request_id")
        or event.get("Input", {}).get("request_id")
        or event.get("body", {}).get("request_id")
    )
    result_obj: Any = (
        event.get("result") or event.get("execute_result") or event.get("body") or event
    )

    if not request_id:
        # Nothing to do without a request id; return gracefully
        return {
            "statusCode": 200,
            "body": {"ok": False, "skipped": "missing_request_id"},
        }

    # DynamoDB lookup for Slack metadata
    region = os.environ.get("AWS_REGION") or "us-east-1"
    table_name = os.environ.get("TABLE_NAME", "")
    if not table_name:
        return {
            "statusCode": 200,
            "body": {"ok": False, "skipped": "missing_table_name"},
        }

    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)
    try:
        item = table.get_item(Key={"request_id": request_id}).get("Item") or {}
    except Exception:
        item = {}

    channel_id: str | None = item.get("slack_channel") or item.get("channel_id")
    ts: str | None = item.get("slack_ts") or item.get("ts")

    if not channel_id or not ts:
        # No Slack metadata to update; consider success
        return {
            "statusCode": 200,
            "body": {"ok": True, "updated": False, "reason": "no_slack_metadata"},
        }

    # Resolve token
    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not bot_token:
        return {"statusCode": 200, "body": {"ok": False, "skipped": "no_token"}}

    # Build text
    text = _extract_text_from_result(result_obj)
    if not text:
        text = "Request completed."

    # Avoid circular import on module import; import at call time
    from src.slack_lambda import _slack_api  # type: ignore

    _slack_api(
        "chat.update",
        bot_token,
        {
            "channel": channel_id,
            "ts": ts,
            "text": text,
        },
    )

    return {"statusCode": 200, "body": {"ok": True, "updated": True}}
