"""
AWS Lambda function for AgentCore Human-in-the-Loop approval processing.

This function handles approval requests, logs them to DynamoDB, and sends
notifications to Slack (Block Kit) and optionally SNS.
"""

import hashlib
import json
import os
import traceback
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any
import logging

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field

from src.dynamodb_utils import get_approval_table
from src.policy import (
    ApprovalOutcome,
    PolicyEngine,
    ProposedAction,
    infer_category_and_resource,
)
from src.slack_blockkit import (
    build_approval_blocks,
    get_header_and_context,
    post_message,
    update_message,
)


class COMPLETION_STATUS(Enum):
    PENDING: str = "pending"
    IN_PROGRESS: str = "in_progress"
    COMPLETED: str = "completed"
    FAILED: str = "failed"
    CANCELED: str = "canceled"


class APPROVAL_COMMUNICATION_STATUS(Enum):
    NOT_SENT: str = "not_sent"
    SENT: str = "sent"
    COMPLETED: str = "completed"
    FAILED: str = "failed"
    CANCELED: str = "canceled"


class ApprovalItem(BaseModel):
    """Pydantic model for approval request items."""

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    approval_communication_status: str = (
        APPROVAL_COMMUNICATION_STATUS.NOT_SENT.value
    )
    requester: str = ""
    approver: str = ""
    agent_prompt: str = ""
    proposed_action: str = ""
    reason: str = ""
    approval_status: ApprovalOutcome = ApprovalOutcome.REQUIRE_APPROVAL
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    # Optional Slack thread metadata for completion updates
    slack_channel: str = ""
    slack_ts: str = ""
    completion_status: str = ""
    completion_message: str = ""

    def to_dynamodb_item(self) -> dict[str, Any]:
        """Convert to DynamoDB item format."""
        return self.model_dump()

    @classmethod
    def from_dynamodb_item(cls, item: dict[str, Any]) -> "ApprovalItem":
        """Create from DynamoDB item."""
        return cls(**item)


class ApprovalDecision(BaseModel):
    """Pydantic model for approval decision requests."""

    request_id: str
    action: ApprovalOutcome = ApprovalOutcome.REQUIRE_APPROVAL
    approver: str = ""
    reason: str = ""


def compute_request_id_from_action(action_text: str) -> str:
    """Compute a deterministic request_id from the proposed action text.

    Uses SHA-256 over the raw UTF-8 bytes of the provided action text and
    returns the hex digest. This ensures identical action texts map to the
    same request_id so we can de-duplicate approval requests.

    Args:
        action_text: The proposed action text to hash.

    Returns:
        Hex-encoded SHA-256 digest string.
    """
    digest = hashlib.sha256(action_text.encode("utf-8")).hexdigest()
    return digest


# Initialize AWS clients
sns = boto3.client("sns", region_name=os.environ["AWS_REGION"])
# Configuration
TABLE_NAME = os.environ["TABLE_NAME"]
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")


# Helper to update Slack message thread
def _slack_update(
    slack_channel: str, slack_ts: str, text: str, blocks: list[dict[str, Any]]
) -> None:
    try:
        if slack_channel and slack_ts:
            update_message(
                slack_channel, slack_ts, text=text, blocks=blocks
            )
    except Exception as e:  # pragma: no cover - best effort
        logging.error(f"Slack update failed: {e}")


def get_lambda_function_url() -> str:
    """
    Resolve the Lambda Function URL for approval action links.

    Returns:
        The Lambda function URL or empty string if not available
    """
    lambda_client = boto3.client(
        "lambda", region_name=os.environ["AWS_REGION"]
    )
    function_name = os.environ.get("APPROVAL_LAMBDA_FUNCTION_NAME", "")
    if not function_name:
        return ""
    try:
        response = lambda_client.get_function_url_config(
            FunctionName=function_name
        )
        return response.get("FunctionUrl", "")
    except Exception:
        return ""


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for processing approval requests and decisions.

    Args:
        event: Lambda event containing request data
        context: Lambda context object

    Returns:
        Response dictionary with status and data
    """
    import base64
    import json
    from urllib.parse import unquote

    try:
        # Handle approval decision (POST with approval data)
        # Opportunistic validation to surface parsing errors early (helps tests and debugging)
        body = event.get("body")
        if event.get("isBase64Encoded"):
            event["body"] = {}
            event["body"]["request_id"] = list(
                {
                    json.loads(g.get("value")).get("request_id")
                    for g in [
                        f.get("elements")
                        for f in json.loads(
                            unquote(base64.b64decode(body)).replace(
                                "payload=", ""
                            )
                        )
                        .get("message")
                        .get("blocks")
                        if f.get("elements")
                    ][0]
                }
            )[0]
            event["body"]["action"] = json.loads(
                unquote(base64.b64decode(body)).replace("payload=", "")
            )["actions"][0]["action_id"]

        # Route the request
        if _is_approval_decision(event):
            return _handle_approval_decision(event)

        # Handle status check (existing request ID lookup)
        else:
            return _handle_status_check(event)

    except Exception as e:
        error_response = {"error": "operation failed", "details": str(e)}
        traceback.print_exc()
        return {"statusCode": 500, "body": json.dumps(error_response)}


def _is_approval_decision(event) -> bool:
    """Check if the event represents an approval decision."""
    # Check for direct approval decision in body
    body = event.get("body") or event.get("Input", {}).get("body")
    if isinstance(body, str):
        try:
            parsed_body = json.loads(body)
            return "action" in parsed_body and "request_id" in parsed_body
        except (json.JSONDecodeError, TypeError):
            pass
    elif isinstance(body, dict):
        return "action" in body and "request_id" in body
    query_params = event.get("queryStringParameters") or {}
    return "action" in query_params and "request_id" in query_params


def _extract_request_id_for_status_check(event: dict[str, Any]) -> str:
    """Extract request_id from various possible event structures."""
    # Try direct access first
    if event.get("request_id"):
        return event["request_id"]

    if event.get("Input", {}).get("request_id"):
        return event["Input"]["request_id"]

    # Step Functions Input format
    if event.get("Input", {}).get("body", {}).get("request_id"):
        return event["Input"]["body"]["request_id"]

    # Direct body access
    body = event.get("body")
    if isinstance(body, dict) and body.get("request_id"):
        return body["request_id"]
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict) and parsed.get("request_id"):
                return parsed["request_id"]
        except Exception:
            pass

    # Query parameters
    if event.get("queryStringParameters", {}).get("request_id"):
        return event["queryStringParameters"]["request_id"]

    raise ValueError("No request_id found in event for status check")


def _handle_approval_decision(event: dict[str, Any]) -> dict[str, Any]:
    """Handle approval decision requests."""
    # Extract decision data from event
    decision_data = _extract_decision_data(event)
    decision = ApprovalDecision(**decision_data)

    # Get existing approval item
    approval_item = get_approval_status(decision_data["request_id"])

    # Update approval status
    approval_item.approval_status = decision.action
    approval_item.approver = decision.approver
    if decision.reason:
        approval_item.reason = decision.reason

    # Save updated item to DynamoDB
    get_approval_table().put_item(Item=approval_item.to_dynamodb_item())

    # Send notification about the decision
    send_notifications(
        request_id=approval_item.request_id,
        action=approval_item.approval_status,
        requester=approval_item.requester,
        approver=approval_item.approver,
        agent_prompt=approval_item.agent_prompt,
        proposed_action=approval_item.proposed_action,
        reason=approval_item.reason,
        approval_status=approval_item.approval_status.value,
        slack_ts=approval_item.slack_ts,
        slack_channel=approval_item.slack_channel,
    )
    approval_item.approval_communication_status = (
        APPROVAL_COMMUNICATION_STATUS.SENT.value
    )
    get_approval_table().put_item(Item=approval_item.to_dynamodb_item())

    response_data = {
        "request_id": approval_item.request_id,
        "status": approval_item.approval_status,
        "approver": approval_item.approver,
        "timestamp": approval_item.timestamp,
        "message": f"Request {decision.action} successfully",
    }

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": response_data,
    }


def _extract_decision_data(event: dict[str, Any]) -> dict[str, Any]:
    """Extract decision data from various event formats."""
    # Try body first (POST requests)
    body = (
        event.get("body")
        or event.get("Input", {}).get("body")
        or event.get("queryStringParameters")
        or {}
    )
    if isinstance(body, str):
        try:
            return json.loads(body)
        except (json.JSONDecodeError, TypeError):
            pass

    if "action" in body and "request_id" in body:
        return {
            "request_id": body["request_id"],
            "action": body["action"],
            "approver": body.get("approver", ""),
            "reason": body.get("reason", ""),
        }

    raise ValueError("No valid decision data found in request")


def _handle_status_check(event: dict[str, Any]) -> dict[str, Any]:
    """Handle existing status check requests."""
    request_id = _extract_request_id_for_status_check(event)
    approval_item = get_approval_status(request_id)

    response_data = {
        "request_id": approval_item.request_id,
        "status": approval_item.approval_status,
        "timestamp": approval_item.timestamp,
        "approval_status": approval_item.approval_status,
    }

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": response_data,
    }


def handle_new_approval_request(event: dict[str, Any]) -> dict[str, Any]:
    """Handle new approval request creation."""
    # Create new approval request
    if "Input" in event:
        event = event["Input"]

    proposed_action_text = (event.get("proposed_action") or "").strip()
    
    slack_channel = event.get("slack_channel", "")
    slack_ts = event.get("slack_ts", "")

    # Compute deterministic request_id from action text
    deterministic_request_id = compute_request_id_from_action(
        proposed_action_text
    )
    
    # Evaluate policy using orchestrator policy code
    inferred_category, inferred_resource = infer_category_and_resource(
        proposed_action_text
    )
    proposed_action = ProposedAction(
        tool_name="auto",
        description=proposed_action_text,
        category=inferred_category,
        resource=inferred_resource,
        environment=os.getenv("ENVIRONMENT", "dev"),
        user_id=event.get("requester") or "slack_user",
    )
    
    decision = PolicyEngine().evaluate(proposed_action)
    
    approval_item = ApprovalItem(
        request_id=deterministic_request_id,
        requester=event.get("requester", ""),
        approver=event.get("approver", ""),
        agent_prompt=event.get("agent_prompt", proposed_action_text),
        proposed_action=proposed_action_text,
        reason="Allowed by policy",
        approval_status=str(decision.outcome.value),
        slack_channel=slack_channel,
        slack_ts=slack_ts,
        completion_status=str(COMPLETION_STATUS.PENDING),
        completion_message="",
    )
    
    send_notifications(
        request_id=approval_item.request_id,
        action=approval_item.approval_status,
        requester=approval_item.requester,
        approver=approval_item.approver,
        agent_prompt=approval_item.agent_prompt,
        proposed_action=approval_item.proposed_action,
        reason=approval_item.reason,
    )

    # Upsert record for audit/completion
    approval_item.approval_communication_status = (
        APPROVAL_COMMUNICATION_STATUS.SENT.value
    )

    get_approval_table().put_item(Item=approval_item.to_dynamodb_item())
    blocks = get_header_and_context(
        deterministic_request_id, f"Request {decision.outcome.value}"
    )
    _slack_update(
        slack_channel,
        slack_ts,
        f"Request ID: {deterministic_request_id}\n{decision.rationale}",
        blocks,
    )
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": {
            "request_id": deterministic_request_id,
            "status": decision.outcome,
            "message": decision.rationale,
        },
    }


def send_notifications(
    request_id: str,
    action: str,
    requester: str,
    approver: str,
    agent_prompt: str,
    proposed_action: str,
    reason: str,
    approval_status: str = None,
    slack_ts: str = None,
    slack_channel: str = None,
):
    """
    Send notifications to configured channels.

    Args:
        request_id: Unique request identifier
        action: Approval action (approve/reject/pending)
        requester: Who requested the approval
        approver: Who approved/rejected
        agent_prompt: Original agent prompt
        proposed_action: What action was proposed
        reason: Reason for approval/rejection

    Returns:
        True if any notification was sent successfully
    """
    notification_sent = False
    proposed_action = proposed_action.replace("<@U099WCH3GM9>", "").strip()
    # Prepare message content
    if action == ApprovalOutcome.REQUIRE_APPROVAL:
        action_text = "Pending Approval"
        status = "pending"
    elif action == ApprovalOutcome.ALLOW:
        action_text = "Approved"
        status = "✅ Approved"
    else:  # reject
        action_text = "Rejected"
        status = "❌ Rejected"
    approval_link = f"{get_lambda_function_url()}?request_id={request_id}&action=approve&approver=admin|"
    rejection_link = f"{get_lambda_function_url()}?request_id={request_id}&action=reject&approver=admin|"
    message_content = {
        "title": f"AgentCore HITL {action_text}",
        "request_id": request_id,
        "status": status,
        "requester": requester,
        "approver": approver,
        "agent_prompt": (
            agent_prompt[:500] + "..."
            if len(agent_prompt) > 500
            else agent_prompt
        ),
        "proposed_action": (
            proposed_action[:300] + "..."
            if len(proposed_action) > 300
            else proposed_action
        ),
        "approval_link": approval_link,
        "rejection_link": rejection_link,
        "reason": reason,
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }

    # Slack notifications (Block Kit only)
    try:
        text = f"Request {approval_status}"
        blocks = get_header_and_context(request_id, text)
        update_message(slack_channel, slack_ts, text=text, blocks=blocks)
        if action == ApprovalOutcome.REQUIRE_APPROVAL and not message_content[
            "proposed_action"
        ].startswith("[Slack thread context]"):
            approve_value = json.dumps(
                {"request_id": request_id, "action": ApprovalOutcome.ALLOW},
                separators=(",", ":"),
            )
            reject_value = json.dumps(
                {"request_id": request_id, "action": ApprovalOutcome.DENY},
                separators=(",", ":"),
            )
            blocks = build_approval_blocks(
                title=message_content["title"],
                request_id=request_id,
                requester=requester,
                proposed_action=message_content["proposed_action"],
                approve_value=approve_value,
                reject_value=reject_value,
            )
            if post_message("foo", message_content["title"], blocks=blocks):
                notification_sent = True


    except Exception as e:  # pragma: no cover - defensive
        logging.error(f"Error sending Slack notification: {e}")

    # SNS topic (optional)
    try:
        if SNS_TOPIC_ARN:
            sns_message = format_sns_message(message_content)
            sns.publish(
                TopicArn=SNS_TOPIC_ARN,
                Subject=f"AgentCore HITL {message_content['status']}",
                Message=sns_message,
            )
            notification_sent = True

    except Exception as e:
        logging.error(f"Error sending SNS notification to {SNS_TOPIC_ARN}: {e}")

    return notification_sent


def format_sns_message(content: dict[str, str]) -> str:
    """Format message for SNS notification."""
    base_message = f"""
AgentCore Human-in-the-Loop {content["status"]}

Request ID: {content["request_id"]}
Status: {content["status"]}
Requester: {content["requester"]}
Approver: {content["approver"]}
Timestamp: {content["timestamp"]}

Agent Prompt:
{content["agent_prompt"]}

Proposed Action:
{content["proposed_action"].replace("@AgentCore", "").strip()}

Reason:
{content["reason"]}"""

    # Add approval links only for pending requests
    function_url = get_lambda_function_url()
    if content.get("status") == "pending" and function_url:
        approval_link = f"{function_url}?request_id={content['request_id']}&action=approve|"
        rejection_link = (
            f"{function_url}?request_id={content['request_id']}&action=reject|"
        )

        base_message += f"""

APPROVAL ACTIONS:
Approve: {approval_link}
Reject: {rejection_link}

Note: Click the links above to approve or reject this request."""

    return base_message.strip()


def get_approval_status(request_id: str) -> ApprovalItem | None:
    """
    Retrieve approval status from DynamoDB.

    Args:
        request_id: Unique request identifier

    Returns:
        ApprovalItem or None if not found
    """
    try:
        response = get_approval_table().get_item(
            Key={"request_id": request_id}
        )
        item_data = response.get("Item")
        if item_data:
            return ApprovalItem.from_dynamodb_item(item_data)
        return None
    except ClientError as e:
        return None


if __name__ == "__main__":
    lambda_handler(
        {
            "version": "2.0",
            "routeKey": "$default",
            "rawPath": "/",
            "rawQueryString": "",
            "headers": {
                "content-length": "4070",
                "x-amzn-tls-version": "TLSv1.3",
                "x-forwarded-proto": "https",
                "x-forwarded-port": "443",
                "x-forwarded-for": "54.172.140.67",
                "accept": "application/json,*/*",
                "x-amzn-tls-cipher-suite": "TLS_AES_128_GCM_SHA256",
                "x-amzn-trace-id": "Root=1-68b369fd-11541f9579e1fcf16144050b",
                "host": "dcosfev3cai22cpmk5dek62ete0lklsk.lambda-url.us-west-2.on.aws",
                "content-type": "application/x-www-form-urlencoded",
                "x-slack-request-timestamp": "1756588540",
                "x-slack-signature": "v0=2e90c75b5092579ae1729514133f33fbd1e0466e95b9dbc4fc850ed258d50e67",
                "accept-encoding": "gzip,deflate",
                "user-agent": "Slackbot 1.0 (+https://api.slack.com/robots)",
            },
            "requestContext": {
                "accountId": "anonymous",
                "apiId": "dcosfev3cai22cpmk5dek62ete0lklsk",
                "domainName": "dcosfev3cai22cpmk5dek62ete0lklsk.lambda-url.us-west-2.on.aws",
                "domainPrefix": "dcosfev3cai22cpmk5dek62ete0lklsk",
                "http": {
                    "method": "POST",
                    "path": "/",
                    "protocol": "HTTP/1.1",
                    "sourceIp": "54.172.140.67",
                    "userAgent": "Slackbot 1.0 (+https://api.slack.com/robots)",
                },
                "requestId": "a659fb90-cee9-4f42-b254-321da2ed8062",
                "routeKey": "$default",
                "stage": "$default",
                "time": "30/Aug/2025:21:15:41 +0000",
                "timeEpoch": 1756588541015,
            },
            "body": "cGF5bG9hZD0lN0IlMjJ0eXBlJTIyJTNBJTIyYmxvY2tfYWN0aW9ucyUyMiUyQyUyMnVzZXIlMjIlM0ElN0IlMjJpZCUyMiUzQSUyMlUwNTUxMEYwMVFSJTIyJTJDJTIydXNlcm5hbWUlMjIlM0ElMjJja2luZyUyMiUyQyUyMm5hbWUlMjIlM0ElMjJja2luZyUyMiUyQyUyMnRlYW1faWQlMjIlM0ElMjJUTVM1Rkg5RFklMjIlN0QlMkMlMjJhcGlfYXBwX2lkJTIyJTNBJTIyQTA5OVFIWUJUNlglMjIlMkMlMjJ0b2tlbiUyMiUzQSUyMnpHUU10R0Y5UEFlVUtrellKOUt4NXJaZCUyMiUyQyUyMmNvbnRhaW5lciUyMiUzQSU3QiUyMnR5cGUlMjIlM0ElMjJtZXNzYWdlJTIyJTJDJTIybWVzc2FnZV90cyUyMiUzQSUyMjE3NTY1ODg1MzIuOTUyMjk5JTIyJTJDJTIyY2hhbm5lbF9pZCUyMiUzQSUyMkMwOUJEQTFFMEhKJTIyJTJDJTIyaXNfZXBoZW1lcmFsJTIyJTNBZmFsc2UlN0QlMkMlMjJ0cmlnZ2VyX2lkJTIyJTNBJTIyOTQzMzY2MDMwNDgwNS43NDAxODU1ODc0NzQuZTA3MmIwZWI1Y2I2MDA0ZGQyZjljYzllMGE1NDg1MDQlMjIlMkMlMjJ0ZWFtJTIyJTNBJTdCJTIyaWQlMjIlM0ElMjJUTVM1Rkg5RFklMjIlMkMlMjJkb21haW4lMjIlM0ElMjJuZXdtYXRoZGF0YSUyMiU3RCUyQyUyMmVudGVycHJpc2UlMjIlM0FudWxsJTJDJTIyaXNfZW50ZXJwcmlzZV9pbnN0YWxsJTIyJTNBZmFsc2UlMkMlMjJjaGFubmVsJTIyJTNBJTdCJTIyaWQlMjIlM0ElMjJDMDlCREExRTBISiUyMiUyQyUyMm5hbWUlMjIlM0ElMjJwcml2YXRlZ3JvdXAlMjIlN0QlMkMlMjJtZXNzYWdlJTIyJTNBJTdCJTIyc3VidHlwZSUyMiUzQSUyMmJvdF9tZXNzYWdlJTIyJTJDJTIydGV4dCUyMiUzQSUyMkFnZW50Q29yZStISVRMK1BlbmRpbmcrQXBwcm92YWwrJTJBUmVxdWVzdCtJRCUzQSUyQSU1Q24wOTNiMjQyM2U4YTYzOTAxOGQ0YjRmZGFkNzdhZTJhYjA5NGU4NDUyNDkxOGNlMjk2MDdkODlkY2NlOWZiMjE4KyUyQVJlcXVlc3RlciUzQSUyQSU1Q25ja2luZyU0MG5ld21hdGhkYXRhLmNvbSslMkFQcm9wb3NlZCtBY3Rpb24lM0ElMkElNUNuaG9sYSsrY291bGQreW91K2tpbmRseStyZXZva2UrYWNjZXNzK2ZvcislM0NtYWlsdG8lM0F0ZXN0X3VzZXIlNDBuZXdtYXRoZGF0YS5jb20lN0N0ZXN0X3VzZXIlNDBuZXdtYXRoZGF0YS5jb20lM0Urb24rYXdzK3Byb2plY3QrJTYwYXJuJTNBYXdzJTNBaWFtJTNBJTNBMjg0NzM0NTk0MzEzJTNBcm9sZSU1QyUyRk5NRC1BZG1pbi1Kb3Vybnl6TmV3TWF0aCUyQ2FybiUzQWF3cyUzQWlhbSUzQSUzQTI4NDczNDU5NDMxMyUzQXNhbWwtcHJvdmlkZXIlNUMlMkZOTURHb29nbGUlNjArK3BsZWFzZSthbmQrdGhhbmsreW91JTIxK0FwcHJvdmUrYnV0dG9uK1JlamVjdCtidXR0b24lMjIlMkMlMjJ0eXBlJTIyJTNBJTIybWVzc2FnZSUyMiUyQyUyMnRzJTIyJTNBJTIyMTc1NjU4ODUzMi45NTIyOTklMjIlMkMlMjJib3RfaWQlMjIlM0ElMjJCMDlDWExaMVI4QyUyMiUyQyUyMmJsb2NrcyUyMiUzQSU1QiU3QiUyMnR5cGUlMjIlM0ElMjJoZWFkZXIlMjIlMkMlMjJibG9ja19pZCUyMiUzQSUyMmF4JTJCUnUlMjIlMkMlMjJ0ZXh0JTIyJTNBJTdCJTIydHlwZSUyMiUzQSUyMnBsYWluX3RleHQlMjIlMkMlMjJ0ZXh0JTIyJTNBJTIyQWdlbnRDb3JlK0hJVEwrUGVuZGluZytBcHByb3ZhbCUyMiUyQyUyMmVtb2ppJTIyJTNBdHJ1ZSU3RCU3RCUyQyU3QiUyMnR5cGUlMjIlM0ElMjJzZWN0aW9uJTIyJTJDJTIyYmxvY2tfaWQlMjIlM0ElMjJrOHVmViUyMiUyQyUyMmZpZWxkcyUyMiUzQSU1QiU3QiUyMnR5cGUlMjIlM0ElMjJtcmtkd24lMjIlMkMlMjJ0ZXh0JTIyJTNBJTIyJTJBUmVxdWVzdCtJRCUzQSUyQSU1Q24wOTNiMjQyM2U4YTYzOTAxOGQ0YjRmZGFkNzdhZTJhYjA5NGU4NDUyNDkxOGNlMjk2MDdkODlkY2NlOWZiMjE4JTIyJTJDJTIydmVyYmF0aW0lMjIlM0FmYWxzZSU3RCUyQyU3QiUyMnR5cGUlMjIlM0ElMjJtcmtkd24lMjIlMkMlMjJ0ZXh0JTIyJTNBJTIyJTJBUmVxdWVzdGVyJTNBJTJBJTVDbiUzQ21haWx0byUzQWNraW5nJTQwbmV3bWF0aGRhdGEuY29tJTdDY2tpbmclNDBuZXdtYXRoZGF0YS5jb20lM0UlMjIlMkMlMjJ2ZXJiYXRpbSUyMiUzQWZhbHNlJTdEJTVEJTdEJTJDJTdCJTIydHlwZSUyMiUzQSUyMnNlY3Rpb24lMjIlMkMlMjJibG9ja19pZCUyMiUzQSUyMjBDNldzJTIyJTJDJTIydGV4dCUyMiUzQSU3QiUyMnR5cGUlMjIlM0ElMjJtcmtkd24lMjIlMkMlMjJ0ZXh0JTIyJTNBJTIyJTJBUHJvcG9zZWQrQWN0aW9uJTNBJTJBJTVDbmhvbGErK2NvdWxkK3lvdStraW5kbHkrcmV2b2tlK2FjY2Vzcytmb3IrJTNDbWFpbHRvJTNBdGVzdF91c2VyJTQwbmV3bWF0aGRhdGEuY29tJTdDdGVzdF91c2VyJTQwbmV3bWF0aGRhdGEuY29tJTNFK29uK2F3cytwcm9qZWN0KyU2MGFybiUzQWF3cyUzQWlhbSUzQSUzQTI4NDczNDU5NDMxMyUzQXJvbGUlNUMlMkZOTUQtQWRtaW4tSm91cm55ek5ld01hdGglMkNhcm4lM0Fhd3MlM0FpYW0lM0ElM0EyODQ3MzQ1OTQzMTMlM0FzYW1sLXByb3ZpZGVyJTVDJTJGTk1ER29vZ2xlJTYwKytwbGVhc2UrYW5kK3RoYW5rK3lvdSUyMSUyMiUyQyUyMnZlcmJhdGltJTIyJTNBZmFsc2UlN0QlN0QlMkMlN0IlMjJ0eXBlJTIyJTNBJTIyYWN0aW9ucyUyMiUyQyUyMmJsb2NrX2lkJTIyJTNBJTIyQkxqelAlMjIlMkMlMjJlbGVtZW50cyUyMiUzQSU1QiU3QiUyMnR5cGUlMjIlM0ElMjJidXR0b24lMjIlMkMlMjJhY3Rpb25faWQlMjIlM0ElMjJBcHByb3ZlZCUyMiUyQyUyMnRleHQlMjIlM0ElN0IlMjJ0eXBlJTIyJTNBJTIycGxhaW5fdGV4dCUyMiUyQyUyMnRleHQlMjIlM0ElMjJBcHByb3ZlJTIyJTJDJTIyZW1vamklMjIlM0F0cnVlJTdEJTJDJTIyc3R5bGUlMjIlM0ElMjJwcmltYXJ5JTIyJTJDJTIydmFsdWUlMjIlM0ElMjIlN0IlNUMlMjJyZXF1ZXN0X2lkJTVDJTIyJTNBJTVDJTIyMDkzYjI0MjNlOGE2MzkwMThkNGI0ZmRhZDc3YWUyYWIwOTRlODQ1MjQ5MThjZTI5NjA3ZDg5ZGNjZTlmYjIxOCU1QyUyMiUyQyU1QyUyMmFjdGlvbiU1QyUyMiUzQSU1QyUyMkFwcHJvdmVkJTVDJTIyJTdEJTIyJTdEJTJDJTdCJTIydHlwZSUyMiUzQSUyMmJ1dHRvbiUyMiUyQyUyMmFjdGlvbl9pZCUyMiUzQSUyMkRlbmllZCUyMiUyQyUyMnRleHQlMjIlM0ElN0IlMjJ0eXBlJTIyJTNBJTIycGxhaW5fdGV4dCUyMiUyQyUyMnRleHQlMjIlM0ElMjJSZWplY3QlMjIlMkMlMjJlbW9qaSUyMiUzQXRydWUlN0QlMkMlMjJzdHlsZSUyMiUzQSUyMmRhbmdlciUyMiUyQyUyMnZhbHVlJTIyJTNBJTIyJTdCJTVDJTIycmVxdWVzdF9pZCU1QyUyMiUzQSU1QyUyMjA5M2IyNDIzZThhNjM5MDE4ZDRiNGZkYWQ3N2FlMmFiMDk0ZTg0NTI0OTE4Y2UyOTYwN2Q4OWRjY2U5ZmIyMTglNUMlMjIlMkMlNUMlMjJhY3Rpb24lNUMlMjIlM0ElNUMlMjJEZW5pZWQlNUMlMjIlN0QlMjIlN0QlNUQlN0QlNUQlN0QlMkMlMjJzdGF0ZSUyMiUzQSU3QiUyMnZhbHVlcyUyMiUzQSU3QiU3RCU3RCUyQyUyMnJlc3BvbnNlX3VybCUyMiUzQSUyMmh0dHBzJTNBJTVDJTJGJTVDJTJGaG9va3Muc2xhY2suY29tJTVDJTJGYWN0aW9ucyU1QyUyRlRNUzVGSDlEWSU1QyUyRjk0MzM2NjAzMDQ3MDklNUMlMkZmdTlXUDJvMGV0a2JkRDdRY2pQRXhYRGolMjIlMkMlMjJhY3Rpb25zJTIyJTNBJTVCJTdCJTIyYWN0aW9uX2lkJTIyJTNBJTIyQXBwcm92ZWQlMjIlMkMlMjJibG9ja19pZCUyMiUzQSUyMkJManpQJTIyJTJDJTIydGV4dCUyMiUzQSU3QiUyMnR5cGUlMjIlM0ElMjJwbGFpbl90ZXh0JTIyJTJDJTIydGV4dCUyMiUzQSUyMkFwcHJvdmUlMjIlMkMlMjJlbW9qaSUyMiUzQXRydWUlN0QlMkMlMjJ2YWx1ZSUyMiUzQSUyMiU3QiU1QyUyMnJlcXVlc3RfaWQlNUMlMjIlM0ElNUMlMjIwOTNiMjQyM2U4YTYzOTAxOGQ0YjRmZGFkNzdhZTJhYjA5NGU4NDUyNDkxOGNlMjk2MDdkODlkY2NlOWZiMjE4JTVDJTIyJTJDJTVDJTIyYWN0aW9uJTVDJTIyJTNBJTVDJTIyQXBwcm92ZWQlNUMlMjIlN0QlMjIlMkMlMjJzdHlsZSUyMiUzQSUyMnByaW1hcnklMjIlMkMlMjJ0eXBlJTIyJTNBJTIyYnV0dG9uJTIyJTJDJTIyYWN0aW9uX3RzJTIyJTNBJTIyMTc1NjU4ODU0MC44Mjk3OTglMjIlN0QlNUQlN0Q=",
            "isBase64Encoded": True,
        },
        {},
    )
