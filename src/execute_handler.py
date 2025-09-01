"""
AWS Lambda function for executing approved MCP actions.

This function loads an MCP server and executes approved actions
based on the approval request ID.
"""

import asyncio
import json
import logging
import os
import sys
import traceback
from datetime import UTC, datetime
from pprint import pprint
from typing import Any

from pydantic import BaseModel, Field

from src.approval_handler import COMPLETION_STATUS, get_approval_status
from src.mcp_client import invoke_mcp_client
from src.policy import ApprovalOutcome

logger = logging.getLogger(__name__)
# Set up more detailed logging for debugging
logging.basicConfig(
    level=logging.ERROR,
    format="%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# Also enable debug logging for related libraries
logging.getLogger("pydantic_ai").setLevel(logging.DEBUG)
logging.getLogger("asyncio").setLevel(logging.DEBUG)

from src.dynamodb_utils import get_approval_table

# Centralized DynamoDB table handle
table = get_approval_table()


class ExecutionRequest(BaseModel):
    """Pydantic model for execution requests."""

    request_id: str | None = Field(
        None, description="Request ID to look up action from DynamoDB"
    )
    action_text: str | None = Field(
        None, description="The natural language action to execute"
    )
    execution_timeout: int = Field(
        default=300, description="Timeout for execution in seconds"
    )


class ExecutionResult(BaseModel):
    """Pydantic model for execution results."""

    request_id: str
    execution_status: str  # "success", "failed", "timeout"
    result: Any = None
    error_message: str | None = None
    execution_time: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for executing MCP actions from natural language text.

    Args:
        event: Lambda event containing execution request with action_text
        context: Lambda context object

    Returns:
        Response dictionary with execution results
    """

    try:
        logger.info(
            f"Execute Lambda received event: {json.dumps(event, default=str)}"
        )

        # Extract request data from event
        if "body" in event:
            if isinstance(event["body"], str):
                body = json.loads(event["body"])
            else:
                body = event["body"]
        else:
            body = event

        logger.debug(f"Parsed request body: {body}")

        # Create execution request
        execution_request = ExecutionRequest(**body)
        logger.debug(f"Created execution request: {execution_request}")

        if execution_request.request_id:
            logger.debug(
                f"Looking up action from DynamoDB for request_id: {execution_request.request_id}"
            )
            # Look up the proposed_action from DynamoDB using request_id
            approval_item = get_approval_status(execution_request.request_id)

            response_body = ""
            if not approval_item:
                raise ValueError(
                    f"Request ID {execution_request.request_id} not found in approval log"
                )
            if approval_item.approval_status != ApprovalOutcome.ALLOW:
                raise ValueError(
                    f"Request {execution_request.request_id} is not approved (status: {approval_item.approval_status})"
                )
            elif approval_item.approval_status == ApprovalOutcome.ALLOW:
                action_text = approval_item.proposed_action
                request_id = execution_request.request_id or "direct_execution"
                combined_query = (
                    f"{getattr(approval_item, 'agent_prompt', '')}\n\n{action_text}"
                    if getattr(approval_item, "agent_prompt", None)
                    else action_text
                )
                response_body = asyncio.run(
                    invoke_mcp_client(combined_query, approval_item.requester)
                )
                table.update_item(
                    Key={"request_id": request_id},
                    UpdateExpression="SET completion_status = :status, completion_message = :message",
                    ExpressionAttributeValues={
                        ":status": str(COMPLETION_STATUS.COMPLETED),
                        ":message": response_body,
                    },
                )
            action_text = approval_item.proposed_action
            request_id = execution_request.request_id
            logger.debug(f"Retrieved action from DynamoDB: {action_text}")

        else:
            raise ValueError(
                "Either action_text or request_id must be provided"
            )

        result = {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": response_body,
        }

        return result

    except Exception as e:
        logger.error(f"Lambda execution failed: {e}")
        logger.error(f"Lambda exception type: {type(e)}")
        logger.error(f"Lambda exception traceback: {traceback.format_exc()}")

        error_response = {
            "error": "execution failed",
            "details": str(e),
            "exception_type": str(type(e)),
        }
        # Attempt to persist failure details to DynamoDB for notifier
        try:
            req_id = None
            # Extract request_id best-effort from the event
            if isinstance(event, dict):
                body = event.get("body", event)
                if isinstance(body, str):
                    try:
                        body = json.loads(body)
                    except Exception:
                        body = {}
                if isinstance(body, dict):
                    req_id = body.get("request_id")
            if req_id:
                table.update_item(
                    Key={"request_id": req_id},
                    UpdateExpression="SET completion_status = :status, completion_message = :message",
                    ExpressionAttributeValues={
                        ":status": str(COMPLETION_STATUS.FAILED),
                        ":message": json.dumps(error_response, default=str),
                    },
                )
        except Exception:
            # Best effort; do not mask original error
            pass

        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": error_response,
        }


if __name__ == "__main__":
    pprint(
        lambda_handler(
            {
                "body": (
                    "{"
                    '"execution_timeout": 300,'
                    '"request_id": "cde914de3cebb4d18c35fb19231089921c3811766d8abd7b416f478627d92569"'
                    "}"
                )
            },
            {},
        )
    )
