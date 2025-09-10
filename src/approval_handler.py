"""
AWS Lambda function for AgentCore Human-in-the-Loop approval processing.

This function handles approval requests, logs them to DynamoDB, and sends
notifications to Slack (Block Kit) and optionally SNS.
"""

import hashlib
import json
import logging
import os
import traceback
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any
import base64
import json
from urllib.parse import unquote
import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field

from src.dynamodb_utils import get_approval_table
from src.config_store import get_mcp_servers
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
from src.constants import REQUEST_ID_LENGTH

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
    # Tools the agent intends to use for this action (fully-qualified IDs
    # such as "google__users_lookup").
    intended_tools: list[str] = Field(default_factory=list)
    # Final set of allowed tool IDs authorized by the approver/policy. The
    # executor must enforce this allowlist at runtime.
    allowed_tools: list[str] = Field(default_factory=list)

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
            event["body"]["approver"] = json.loads(unquote(base64.b64decode(body)).replace('payload=','')).get('user').get('username')

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
    if "action" in event and "request_id" in event:
        return True
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
    if "action" in event and "request_id" in event:
        return {
            "request_id": event["request_id"],
            "action": event["action"],
            "approver": event.get("approver", ""),
            "reason": event.get("reason", ""),
        }
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
        intended_tools=[inferred_resource],
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
        intended_tools=[inferred_resource],
        allowed_tools=[inferred_resource],
    )

    send_notifications(
        request_id=approval_item.request_id,
        action=approval_item.approval_status,
        requester=approval_item.requester,
        approver=approval_item.approver,
        agent_prompt=approval_item.agent_prompt,
        proposed_action=approval_item.proposed_action,
        proposed_tool=inferred_resource,
        reason=approval_item.reason,
    )

    # Upsert record for audit/completion
    approval_item.approval_communication_status = (
        APPROVAL_COMMUNICATION_STATUS.SENT.value
    )
    print(f"Approval item: {approval_item}")
    print(f"Approval item: {approval_item.to_dynamodb_item()}")
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
    proposed_tool: str = None,
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
                proposed_tool=proposed_tool,
            )
            if post_message("foo", message_content["title"], blocks=blocks):
                notification_sent = True
        if action in [ApprovalOutcome.ALLOW, ApprovalOutcome.DENY]:
            post_message("foo", text=f"Request {request_id[:REQUEST_ID_LENGTH]}: {approval_status} by {approver}")


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
    except ClientError:
        return None


if __name__ == "__main__":
    lambda_handler(
        {'version': '2.0', 'routeKey': '$default', 'rawPath': '/', 'rawQueryString': '', 'headers': {'content-length': '3886', 'x-amzn-tls-version': 'TLSv1.3', 'x-forwarded-proto': 'https', 'x-forwarded-port': '443', 'x-forwarded-for': '44.203.16.149', 'accept': 'application/json,*/*', 'x-amzn-tls-cipher-suite': 'TLS_AES_128_GCM_SHA256', 'x-amzn-trace-id': 'Root=1-68c1a2fc-37ecf8d371c3cd0467aaadcf', 'host': 'dcosfev3cai22cpmk5dek62ete0lklsk.lambda-url.us-west-2.on.aws', 'content-type': 'application/x-www-form-urlencoded', 'x-slack-request-timestamp': '1757520635', 'x-slack-signature': 'v0=3d5ba5fff3eb01045b2d6158b868d2a81a77de64e414a76a93fce61a8a1f294e', 'accept-encoding': 'gzip,deflate', 'user-agent': 'Slackbot 1.0 (+https://api.slack.com/robots)'}, 'requestContext': {'accountId': 'anonymous', 'apiId': 'dcosfev3cai22cpmk5dek62ete0lklsk', 'domainName': 'dcosfev3cai22cpmk5dek62ete0lklsk.lambda-url.us-west-2.on.aws', 'domainPrefix': 'dcosfev3cai22cpmk5dek62ete0lklsk', 'http': {'method': 'POST', 'path': '/', 'protocol': 'HTTP/1.1', 'sourceIp': '44.203.16.149', 'userAgent': 'Slackbot 1.0 (+https://api.slack.com/robots)'}, 'requestId': '6c0097df-b885-41c2-9104-0406ebed7616', 'routeKey': '$default', 'stage': '$default', 'time': '10/Sep/2025:16:10:36 +0000', 'timeEpoch': 1757520636088}, 'body': 'cGF5bG9hZD0lN0IlMjJ0eXBlJTIyJTNBJTIyYmxvY2tfYWN0aW9ucyUyMiUyQyUyMnVzZXIlMjIlM0ElN0IlMjJpZCUyMiUzQSUyMlUwNTUxMEYwMVFSJTIyJTJDJTIydXNlcm5hbWUlMjIlM0ElMjJja2luZyUyMiUyQyUyMm5hbWUlMjIlM0ElMjJja2luZyUyMiUyQyUyMnRlYW1faWQlMjIlM0ElMjJUTVM1Rkg5RFklMjIlN0QlMkMlMjJhcGlfYXBwX2lkJTIyJTNBJTIyQTA5OVFIWUJUNlglMjIlMkMlMjJ0b2tlbiUyMiUzQSUyMnpHUU10R0Y5UEFlVUtrellKOUt4NXJaZCUyMiUyQyUyMmNvbnRhaW5lciUyMiUzQSU3QiUyMnR5cGUlMjIlM0ElMjJtZXNzYWdlJTIyJTJDJTIybWVzc2FnZV90cyUyMiUzQSUyMjE3NTY5NTUwMzAuMjQ1MDI5JTIyJTJDJTIyY2hhbm5lbF9pZCUyMiUzQSUyMkMwOUJEQTFFMEhKJTIyJTJDJTIyaXNfZXBoZW1lcmFsJTIyJTNBZmFsc2UlN0QlMkMlMjJ0cmlnZ2VyX2lkJTIyJTNBJTIyOTUyMjM0NzUyODk0NC43NDAxODU1ODc0NzQuNzRiY2U5ZmRiNDQ3NGEyNDk3ZmJkOWQ0N2UzNjRhNzAlMjIlMkMlMjJ0ZWFtJTIyJTNBJTdCJTIyaWQlMjIlM0ElMjJUTVM1Rkg5RFklMjIlMkMlMjJkb21haW4lMjIlM0ElMjJuZXdtYXRoZGF0YSUyMiU3RCUyQyUyMmVudGVycHJpc2UlMjIlM0FudWxsJTJDJTIyaXNfZW50ZXJwcmlzZV9pbnN0YWxsJTIyJTNBZmFsc2UlMkMlMjJjaGFubmVsJTIyJTNBJTdCJTIyaWQlMjIlM0ElMjJDMDlCREExRTBISiUyMiUyQyUyMm5hbWUlMjIlM0ElMjJwcml2YXRlZ3JvdXAlMjIlN0QlMkMlMjJtZXNzYWdlJTIyJTNBJTdCJTIyc3VidHlwZSUyMiUzQSUyMmJvdF9tZXNzYWdlJTIyJTJDJTIydGV4dCUyMiUzQSUyMkFnZW50Q29yZStISVRMK1BlbmRpbmcrQXBwcm92YWwrJTJBUmVxdWVzdCtJRCUzQSUyQSU1Q245MmYzZmE4ZmE1YWI2OTAyZDljM2JkM2NhZTRhNjdmNGFkZDg1ZjUwYTkyNWNmYzhjMjgyYjY5N2I0ZWNkYWFmKyUyQVJlcXVlc3RlciUzQSUyQSU1Q25ja2luZyU0MG5ld21hdGhkYXRhLmNvbSslMkFQcm9wb3NlZCtBY3Rpb24lM0ElMkElNUNudW5zdXNwZW5kK2dvb2dsZSt1c2VyK3Rlc3RfdXNlciU0MG5ld21hdGhkYXRhLmNvbSslMkFQcm9wb3NlZCtUb29sJTNBJTJBJTVDbmdvb2dsZV9hZG1pbl9fdW5zdXNwZW5kX3VzZXIrQXBwcm92ZStidXR0b24rUmVqZWN0K2J1dHRvbiUyMiUyQyUyMnR5cGUlMjIlM0ElMjJtZXNzYWdlJTIyJTJDJTIydHMlMjIlM0ElMjIxNzU2OTU1MDMwLjI0NTAyOSUyMiUyQyUyMmJvdF9pZCUyMiUzQSUyMkIwOUNYTFoxUjhDJTIyJTJDJTIyYmxvY2tzJTIyJTNBJTVCJTdCJTIydHlwZSUyMiUzQSUyMmhlYWRlciUyMiUyQyUyMmJsb2NrX2lkJTIyJTNBJTIyN0VNWE8lMjIlMkMlMjJ0ZXh0JTIyJTNBJTdCJTIydHlwZSUyMiUzQSUyMnBsYWluX3RleHQlMjIlMkMlMjJ0ZXh0JTIyJTNBJTIyQWdlbnRDb3JlK0hJVEwrUGVuZGluZytBcHByb3ZhbCUyMiUyQyUyMmVtb2ppJTIyJTNBdHJ1ZSU3RCU3RCUyQyU3QiUyMnR5cGUlMjIlM0ElMjJzZWN0aW9uJTIyJTJDJTIyYmxvY2tfaWQlMjIlM0ElMjJtNWIyMiUyMiUyQyUyMmZpZWxkcyUyMiUzQSU1QiU3QiUyMnR5cGUlMjIlM0ElMjJtcmtkd24lMjIlMkMlMjJ0ZXh0JTIyJTNBJTIyJTJBUmVxdWVzdCtJRCUzQSUyQSU1Q245MmYzZmE4ZmE1YWI2OTAyZDljM2JkM2NhZTRhNjdmNGFkZDg1ZjUwYTkyNWNmYzhjMjgyYjY5N2I0ZWNkYWFmJTIyJTJDJTIydmVyYmF0aW0lMjIlM0FmYWxzZSU3RCUyQyU3QiUyMnR5cGUlMjIlM0ElMjJtcmtkd24lMjIlMkMlMjJ0ZXh0JTIyJTNBJTIyJTJBUmVxdWVzdGVyJTNBJTJBJTVDbiUzQ21haWx0byUzQWNraW5nJTQwbmV3bWF0aGRhdGEuY29tJTdDY2tpbmclNDBuZXdtYXRoZGF0YS5jb20lM0UlMjIlMkMlMjJ2ZXJiYXRpbSUyMiUzQWZhbHNlJTdEJTVEJTdEJTJDJTdCJTIydHlwZSUyMiUzQSUyMnNlY3Rpb24lMjIlMkMlMjJibG9ja19pZCUyMiUzQSUyMllVQUduJTIyJTJDJTIydGV4dCUyMiUzQSU3QiUyMnR5cGUlMjIlM0ElMjJtcmtkd24lMjIlMkMlMjJ0ZXh0JTIyJTNBJTIyJTJBUHJvcG9zZWQrQWN0aW9uJTNBJTJBJTVDbnVuc3VzcGVuZCtnb29nbGUrdXNlcislM0NtYWlsdG8lM0F0ZXN0X3VzZXIlNDBuZXdtYXRoZGF0YS5jb20lN0N0ZXN0X3VzZXIlNDBuZXdtYXRoZGF0YS5jb20lM0UlMjIlMkMlMjJ2ZXJiYXRpbSUyMiUzQWZhbHNlJTdEJTdEJTJDJTdCJTIydHlwZSUyMiUzQSUyMnNlY3Rpb24lMjIlMkMlMjJibG9ja19pZCUyMiUzQSUyMjBTekViJTIyJTJDJTIydGV4dCUyMiUzQSU3QiUyMnR5cGUlMjIlM0ElMjJtcmtkd24lMjIlMkMlMjJ0ZXh0JTIyJTNBJTIyJTJBUHJvcG9zZWQrVG9vbCUzQSUyQSU1Q25nb29nbGVfYWRtaW5fX3Vuc3VzcGVuZF91c2VyJTIyJTJDJTIydmVyYmF0aW0lMjIlM0FmYWxzZSU3RCU3RCUyQyU3QiUyMnR5cGUlMjIlM0ElMjJhY3Rpb25zJTIyJTJDJTIyYmxvY2tfaWQlMjIlM0ElMjIyYmlpTyUyMiUyQyUyMmVsZW1lbnRzJTIyJTNBJTVCJTdCJTIydHlwZSUyMiUzQSUyMmJ1dHRvbiUyMiUyQyUyMmFjdGlvbl9pZCUyMiUzQSUyMkFwcHJvdmVkJTIyJTJDJTIydGV4dCUyMiUzQSU3QiUyMnR5cGUlMjIlM0ElMjJwbGFpbl90ZXh0JTIyJTJDJTIydGV4dCUyMiUzQSUyMkFwcHJvdmUlMjIlMkMlMjJlbW9qaSUyMiUzQXRydWUlN0QlMkMlMjJzdHlsZSUyMiUzQSUyMnByaW1hcnklMjIlMkMlMjJ2YWx1ZSUyMiUzQSUyMiU3QiU1QyUyMnJlcXVlc3RfaWQlNUMlMjIlM0ElNUMlMjI5MmYzZmE4ZmE1YWI2OTAyZDljM2JkM2NhZTRhNjdmNGFkZDg1ZjUwYTkyNWNmYzhjMjgyYjY5N2I0ZWNkYWFmJTVDJTIyJTJDJTVDJTIyYWN0aW9uJTVDJTIyJTNBJTVDJTIyQXBwcm92ZWQlNUMlMjIlN0QlMjIlN0QlMkMlN0IlMjJ0eXBlJTIyJTNBJTIyYnV0dG9uJTIyJTJDJTIyYWN0aW9uX2lkJTIyJTNBJTIyRGVuaWVkJTIyJTJDJTIydGV4dCUyMiUzQSU3QiUyMnR5cGUlMjIlM0ElMjJwbGFpbl90ZXh0JTIyJTJDJTIydGV4dCUyMiUzQSUyMlJlamVjdCUyMiUyQyUyMmVtb2ppJTIyJTNBdHJ1ZSU3RCUyQyUyMnN0eWxlJTIyJTNBJTIyZGFuZ2VyJTIyJTJDJTIydmFsdWUlMjIlM0ElMjIlN0IlNUMlMjJyZXF1ZXN0X2lkJTVDJTIyJTNBJTVDJTIyOTJmM2ZhOGZhNWFiNjkwMmQ5YzNiZDNjYWU0YTY3ZjRhZGQ4NWY1MGE5MjVjZmM4YzI4MmI2OTdiNGVjZGFhZiU1QyUyMiUyQyU1QyUyMmFjdGlvbiU1QyUyMiUzQSU1QyUyMkRlbmllZCU1QyUyMiU3RCUyMiU3RCU1RCU3RCU1RCU3RCUyQyUyMnN0YXRlJTIyJTNBJTdCJTIydmFsdWVzJTIyJTNBJTdCJTdEJTdEJTJDJTIycmVzcG9uc2VfdXJsJTIyJTNBJTIyaHR0cHMlM0ElNUMlMkYlNUMlMkZob29rcy5zbGFjay5jb20lNUMlMkZhY3Rpb25zJTVDJTJGVE1TNUZIOURZJTVDJTJGOTUyMjM0NzQ4NDY1NiU1QyUyRkg3ZW1tYTFCbzRTd3JaYkxUdWhGNkhSciUyMiUyQyUyMmFjdGlvbnMlMjIlM0ElNUIlN0IlMjJhY3Rpb25faWQlMjIlM0ElMjJBcHByb3ZlZCUyMiUyQyUyMmJsb2NrX2lkJTIyJTNBJTIyMmJpaU8lMjIlMkMlMjJ0ZXh0JTIyJTNBJTdCJTIydHlwZSUyMiUzQSUyMnBsYWluX3RleHQlMjIlMkMlMjJ0ZXh0JTIyJTNBJTIyQXBwcm92ZSUyMiUyQyUyMmVtb2ppJTIyJTNBdHJ1ZSU3RCUyQyUyMnZhbHVlJTIyJTNBJTIyJTdCJTVDJTIycmVxdWVzdF9pZCU1QyUyMiUzQSU1QyUyMjkyZjNmYThmYTVhYjY5MDJkOWMzYmQzY2FlNGE2N2Y0YWRkODVmNTBhOTI1Y2ZjOGMyODJiNjk3YjRlY2RhYWYlNUMlMjIlMkMlNUMlMjJhY3Rpb24lNUMlMjIlM0ElNUMlMjJBcHByb3ZlZCU1QyUyMiU3RCUyMiUyQyUyMnN0eWxlJTIyJTNBJTIycHJpbWFyeSUyMiUyQyUyMnR5cGUlMjIlM0ElMjJidXR0b24lMjIlMkMlMjJhY3Rpb25fdHMlMjIlM0ElMjIxNzU3NTIwNjM1LjkwMzMyMiUyMiU3RCU1RCU3RA==', 'isBase64Encoded': True},
        {},
    )
