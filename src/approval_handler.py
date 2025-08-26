"""
AWS Lambda function for AgentCore Human-in-the-Loop approval processing.

This function handles approval requests, logs them to DynamoDB, and sends
notifications to Slack or Microsoft Teams.
"""

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import boto3
import requests
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field

from src.policy import (
    ApprovalOutcome,
    PolicyEngine,
    ProposedAction,
    infer_category_and_resource,
)


class COMPLETION_STATUS(Enum):
    PENDING: str = "pending"
    IN_PROGRESS: str = "in_progress"
    COMPLETED: str = "completed"
    FAILED: str = "failed"
    CANCELED: str = "canceled"


class ApprovalItem(BaseModel):
    """Pydantic model for approval request items."""

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    requester: str = ""
    approver: str = ""
    agent_prompt: str = ""
    proposed_action: str = ""
    reason: str = ""
    approval_status: str = "pending"
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


class ApprovalDecision(BaseModel):
    """Pydantic model for approval decision requests."""

    request_id: str
    action: str = Field(..., pattern="^(approve|reject)$")
    approver: str = ""
    reason: str = ""


if os.getenv("LOCAL_DEV", "false") == "true":
    ddb_params = {
        "endpoint_url": "http://agentcore-dynamodb-local:8000",
        "aws_access_key_id": "test",
        "aws_secret_access_key": "test",
    }
else:
    ddb_params = {}
# Initialize AWS clients
dynamodb = boto3.resource(
    "dynamodb", region_name=os.environ["AWS_REGION"], **ddb_params
)
sns = boto3.client("sns", region_name=os.environ["AWS_REGION"])
# Configuration
TABLE_NAME = os.environ["TABLE_NAME"]
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
# Optional webhook integrations
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
table = dynamodb.Table(TABLE_NAME)


# Helper to update Slack message thread
def _slack_update(slack_channel: str, slack_ts: str, text: str) -> None:
    try:
        if slack_channel and slack_ts:
            from src.slack_lambda import (
                _slack_api,
            )  # lazy import to avoid cycles

            bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
            if bot_token:
                _slack_api(
                    "chat.update",
                    bot_token,
                    {"channel": slack_channel, "ts": slack_ts, "text": text},
                )
    except Exception as e:  # pragma: no cover - best effort
        print(f"Slack update failed: {e}")


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
    import urllib

    print(f"Approval handler received event: {event}")
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
                            urllib.parse.unquote(
                                base64.b64decode(body)
                            ).replace("payload=", "")
                        )
                        .get("message")
                        .get("blocks")
                        if f.get("elements")
                    ][0]
                }
            )[0]
            event["body"]["action"] = json.loads(
                urllib.parse.unquote(base64.b64decode(body)).replace(
                    "payload=", ""
                )
            )["actions"][0]["action_id"]
            print(f"transformed event {event}")
        if body is not None:
            try:
                # This will raise if body is invalid JSON when provided as a string
                _ = _extract_decision_data({"body": event})
            except Exception:
                # Re-raise to be handled by the generic error block below
                raise

        # Route the request
        if _is_approval_decision(event):
            return _handle_approval_decision(event)

        # Handle status check (existing request ID lookup)
        elif _has_request_id_for_status_check(event):
            return _handle_status_check(event)

        # Handle new approval request creation
        else:
            return _handle_new_approval_request(event)

    except Exception as e:
        error_response = {"error": "operation failed", "details": str(e)}
        print(f"error_response {error_response}")
        return {"statusCode": 500, "body": json.dumps(error_response)}


def _is_approval_decision(event: dict[str, Any]) -> bool:
    """Check if the event represents an approval decision."""
    # Check for direct approval decision in body
    body = event.get("body")
    if isinstance(body, str):
        try:
            parsed_body = json.loads(body)
            return "action" in parsed_body and "request_id" in parsed_body
        except (json.JSONDecodeError, TypeError):
            pass
    elif isinstance(body, dict):
        return "action" in body and "request_id" in body

    # Check for query parameters (for GET requests with approval)
    query_params = event.get("queryStringParameters") or {}
    return "action" in query_params and "request_id" in query_params


def _has_request_id_for_status_check(event: dict[str, Any]) -> bool:
    """Check if the event has a request_id for status checking."""
    # Check various possible locations for request_id in Step Functions input
    # Direct access to request_id
    if event.get("request_id"):
        return True

    # Step Functions Input format
    if event.get("Input", {}).get("body", {}).get("request_id"):
        return True

    # Direct body access
    body = event.get("body")
    if isinstance(body, dict) and body.get("request_id"):
        return True
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict) and parsed.get("request_id"):
                return True
        except Exception:
            pass

    # Query parameters
    if event.get("queryStringParameters", {}).get("request_id"):
        return True

    return False


def _extract_request_id_for_status_check(event: dict[str, Any]) -> str:
    """Extract request_id from various possible event structures."""
    # Try direct access first
    if event.get("request_id"):
        return event["request_id"]

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
    print(f"_handle_approval_decision event {event}")
    decision_data = _extract_decision_data(event)
    decision = ApprovalDecision(**decision_data)

    # Get existing approval item
    response = table.get_item(Key={"request_id": decision.request_id})
    item_data = response.get("Item")
    if not item_data:
        raise ValueError(
            f"Request ID {decision.request_id} not found in approval log."
        )

    approval_item = ApprovalItem.from_dynamodb_item(item_data)

    # Update approval status
    approval_item.approval_status = decision.action
    approval_item.approver = decision.approver
    if decision.reason:
        approval_item.reason = decision.reason

    # Update timestamp for the decision
    approval_item.timestamp = datetime.now(UTC).isoformat()

    # Save updated item to DynamoDB
    table.put_item(Item=approval_item.to_dynamodb_item())

    # Send notification about the decision
    send_notifications(
        request_id=approval_item.request_id,
        action=approval_item.approval_status,
        requester=approval_item.requester,
        approver=approval_item.approver,
        agent_prompt=approval_item.agent_prompt,
        proposed_action=approval_item.proposed_action,
        reason=approval_item.reason,
    )

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
    body = event.get("body")
    if isinstance(body, str):
        try:
            return json.loads(body)
        except (json.JSONDecodeError, TypeError):
            pass
    elif isinstance(body, dict):
        return body

    # Try query parameters (GET requests)
    query_params = event.get("queryStringParameters") or {}
    if "action" in query_params and "request_id" in query_params:
        return {
            "request_id": query_params["request_id"],
            "action": query_params["action"],
            "approver": query_params.get("approver", ""),
            "reason": query_params.get("reason", ""),
        }

    raise ValueError("No valid decision data found in request")


def _handle_status_check(event: dict[str, Any]) -> dict[str, Any]:
    """Handle existing status check requests."""
    request_id = _extract_request_id_for_status_check(event)
    response = table.get_item(Key={"request_id": request_id})
    item_data = response.get("Item")
    if not item_data:
        raise ValueError(f"Approval request {request_id} not found")

    approval_item = ApprovalItem.from_dynamodb_item(item_data)

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


def _handle_new_approval_request(event: dict[str, Any]) -> dict[str, Any]:
    """Handle new approval request creation."""
    # Create new approval request
    if "Input" in event:
        event = event["Input"]
    print(f"_handle_new_approval_request event {event}")

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
        approval_status=decision.outcome,
        slack_channel=slack_channel,
        slack_ts=slack_ts,
        completion_status=str(COMPLETION_STATUS.PENDING),
        completion_message=decision.outcome,
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
    table.put_item(Item=approval_item.to_dynamodb_item())
    _slack_update(
        slack_channel,
        slack_ts,
        f"Request ID: {deterministic_request_id}\n{decision.rationale}",
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
) -> bool:
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
    if action == "pending":
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
    print(f"message_content {message_content}")
    # Slack notifications
    try:
        # Prefer Block Kit via bot token and channel when configured
        slack_bot_token = os.environ.get("SLACK_BOT_TOKEN")
        slack_channel_id = os.environ.get("SLACK_CHANNEL_ID")
        if slack_bot_token and slack_channel_id:
            from .slack_helper import post_slack_block_approval

            if action == "pending":
                if post_slack_block_approval(
                    message_content,
                    channel_id=slack_channel_id,
                    bot_token=slack_bot_token,
                ):
                    notification_sent = True
                    print(
                        f"Slack Block Kit message sent for request {request_id}"
                    )
        # Fallback to webhook when configured
        elif SLACK_WEBHOOK_URL:
            from .slack_helper import post_slack_webhook_message

            if post_slack_webhook_message(
                message_content, function_url_getter=get_lambda_function_url
            ):
                notification_sent = True
                print(
                    f"Slack webhook notification sent for request {request_id}"
                )
    except Exception as e:  # pragma: no cover - defensive
        print(f"Error sending Slack notification: {e}")

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
            print(f"SNS notification sent for request {request_id}")
    except Exception as e:
        print(f"Error sending SNS notification to {SNS_TOPIC_ARN}: {e}")

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


def send_slack_notification(content: dict[str, str]) -> bool:
    """Post a simple Slack webhook message for approval notifications.

    Kept for backward-compatibility with tests. Builds text inline and posts
    via requests within this module to allow straightforward patching in tests.
    """
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return False

    # Build text in the same style as slack_helper._build_slack_text
    lines = [
        f"*{content.get('title', 'AgentCore Notification')}*",
        f"*Request ID*: {content.get('request_id', '')}",
        f"*Status*: {content.get('status', '')}",
        f"*Requester*: {content.get('requester', '')}",
        "",
        "*Agent Prompt:*",
        content.get("agent_prompt", ""),
        "",
        "*Proposed Action:*",
        content.get("proposed_action", ""),
    ]
    reason = content.get("reason")
    if reason:
        lines.extend(["", "*Reason:*", reason])

    if content.get("status") == "pending":
        function_url = get_lambda_function_url()
        if function_url:
            rid = content.get("request_id", "")
            approve_link = f"{function_url}?request_id={rid}&action={ApprovalOutcome.ALLOW}"
            reject_link = f"{function_url}?request_id={rid}&action={ApprovalOutcome.DENY}"
            lines.extend(
                [
                    "",
                    "*Approval Actions:*",
                    f"Approve: {approve_link}",
                    f"Reject: {reject_link}",
                ]
            )

    payload = {"text": "\n".join(lines)}
    resp = requests.post(webhook_url, json=payload, timeout=5)
    return resp.status_code == 200 and resp.text.strip().lower() in {"ok", ""}


def get_approval_status(request_id: str) -> ApprovalItem | None:
    """
    Retrieve approval status from DynamoDB.

    Args:
        request_id: Unique request identifier

    Returns:
        ApprovalItem or None if not found
    """
    try:
        response = table.get_item(Key={"request_id": request_id})
        item_data = response.get("Item")
        print(f"Approval item data: {item_data}")
        if item_data:
            return ApprovalItem.from_dynamodb_item(item_data)
        return None
    except ClientError as e:
        print(f"Error retrieving approval status: {e}")
        return None


def read_sns_messages_locally(
    region_name: str = "us-east-1", max_messages: int = 10
) -> list[dict[str, Any]]:
    """
    Read SNS messages locally for testing and debugging.

    Note: This requires the SNS topic to have an SQS subscription for local testing.
    In production, use CloudWatch logs or other monitoring tools.

    Args:
        region_name: AWS region name
        max_messages: Maximum number of messages to retrieve

    Returns:
        List of message dictionaries
    """
    try:
        import boto3
        from botocore.exceptions import (
            NoCredentialsError,
            PartialCredentialsError,
        )

        # Check if we have AWS credentials
        try:
            session = boto3.Session()
            credentials = session.get_credentials()
            if not credentials:
                print(
                    "Warning: No AWS credentials found. Cannot read SNS messages."
                )
                return []
        except (NoCredentialsError, PartialCredentialsError):
            print("Warning: AWS credentials not configured properly.")
            return []

        # For local testing, we would typically need an SQS queue subscribed to the SNS topic
        # This is a placeholder implementation that would need actual SQS integration
        print(f"Reading SNS messages from region: {region_name}")
        print(f"SNS Topic ARN: {SNS_TOPIC_ARN}")
        print(
            "Note: For local testing, subscribe an SQS queue to the SNS topic and read from SQS."
        )

        # TODO: Implement actual SQS message reading
        # sqs = boto3.client('sqs', region_name=region_name)
        # queue_url = "your-test-queue-url"  # Would need to be configured
        # response = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=max_messages)
        # messages = response.get('Messages', [])

        return []

    except Exception as e:
        print(f"Error reading SNS messages: {e}")
        return []


def create_test_sqs_queue_for_sns(
    queue_name: str = "agentcore-sns-test-queue",
    region_name: str = "us-east-1",
) -> str | None:
    """
    Create a test SQS queue and subscribe it to the SNS topic for local testing.

    Args:
        queue_name: Name for the SQS queue
        region_name: AWS region name

    Returns:
        Queue URL if successful, None otherwise
    """
    try:
        import boto3

        sqs = boto3.client("sqs", region_name=region_name)
        sns = boto3.client("sns", region_name=region_name)

        # Create SQS queue
        queue_response = sqs.create_queue(
            QueueName=queue_name,
            Attributes={
                "MessageRetentionPeriod": "1209600",  # 14 days
                "VisibilityTimeoutSeconds": "30",
            },
        )
        queue_url = queue_response["QueueUrl"]

        # Get queue attributes to get the ARN
        queue_attrs = sqs.get_queue_attributes(
            QueueUrl=queue_url, AttributeNames=["QueueArn"]
        )
        queue_arn = queue_attrs["Attributes"]["QueueArn"]

        # Subscribe queue to SNS topic
        if SNS_TOPIC_ARN:
            sns.subscribe(
                TopicArn=SNS_TOPIC_ARN, Protocol="sqs", Endpoint=queue_arn
            )
            print(f"Successfully created test queue: {queue_url}")
            print(f"Subscribed to SNS topic: {SNS_TOPIC_ARN}")
            return queue_url
        else:
            print("Warning: SNS_TOPIC_ARN not configured")
            return queue_url

    except Exception as e:
        print(f"Error creating test SQS queue: {e}")
        return None


def read_messages_from_test_queue(
    queue_url: str, max_messages: int = 10, region_name: str = "us-east-1"
) -> list[dict[str, Any]]:
    """
    Read messages from the test SQS queue to see SNS notifications.

    Args:
        queue_url: SQS queue URL
        max_messages: Maximum number of messages to retrieve
        region_name: AWS region name

    Returns:
        List of parsed message dictionaries
    """
    try:
        import boto3

        sqs = boto3.client("sqs", region_name=region_name)

        response = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=5,
            AttributeNames=["All"],
        )

        messages = response.get("Messages", [])
        parsed_messages = []

        for message in messages:
            try:
                # Parse SNS message body
                body = json.loads(message["Body"])
                sns_message = (
                    json.loads(body["Message"])
                    if isinstance(body.get("Message"), str)
                    else body.get("Message", body)
                )

                parsed_message = {
                    "message_id": message.get("MessageId"),
                    "receipt_handle": message.get("ReceiptHandle"),
                    "sns_subject": body.get("Subject", ""),
                    "sns_message": body.get("Message", ""),
                    "parsed_content": (
                        sns_message if isinstance(sns_message, dict) else {}
                    ),
                    "timestamp": body.get("Timestamp", ""),
                    "raw_body": message["Body"],
                }
                parsed_messages.append(parsed_message)

                # Delete message after reading (optional)
                # sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message['ReceiptHandle'])

            except (json.JSONDecodeError, KeyError) as e:
                print(f"Error parsing message: {e}")
                continue

        return parsed_messages

    except Exception as e:
        print(f"Error reading messages from queue: {e}")
        return []
