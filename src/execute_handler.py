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
from typing import Any
from pprint import pprint   

import boto3
from pydantic import BaseModel, Field

from src.approval_handler import COMPLETION_STATUS, get_approval_status
from src.mcp_client import MCPClient

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

# Initialize AWS clients
if os.getenv("LOCAL_DEV", "false") == "true":
    ddb_params = {
        "endpoint_url": "http://agentcore-dynamodb-local:8000",
        "aws_access_key_id": "test",
        "aws_secret_access_key": "test",
    }
else:
    ddb_params = {}

dynamodb = boto3.resource(
    "dynamodb", region_name=os.environ["AWS_REGION"], **ddb_params
)
TABLE_NAME = os.environ["TABLE_NAME"]
table = dynamodb.Table(TABLE_NAME)


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


async def invoke_mcp_client(action_text: str, requester_email: str = None):
    client = MCPClient()
    try:
        # Prefer multi-server configuration when provided
        servers_env = os.getenv("MCP_SERVERS", "").strip()
        if servers_env:
            alias_to_path: dict[str, str] = {}
            for part in servers_env.split(";"):
                logger.error(f"part: {part} requester_email: {requester_email}")
                if not part or "=" not in part:
                    continue
                alias, path = part.split("=", 1)
                alias_to_path[alias.strip()] = path.strip()
            if alias_to_path:
                await client.connect_to_servers(alias_to_path, requester_email)
        else:
            await client.connect_to_server(
                "google_mcp/google_admin/mcp_server.py",
                requester_email
            )
        result = await client.process_query(action_text, requester_email)
    finally:
        await client.cleanup()
    return result


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
            if approval_item.approval_status != "approve":
                raise ValueError(
                    f"Request {execution_request.request_id} is not approved (status: {approval_item.approval_status})"
                )
            elif approval_item.approval_status == "approve":
                
                
                action_text = approval_item.proposed_action
                request_id = execution_request.request_id or "direct_execution"
                logger.error(
                    f"Executing action for request {request_id} on behalf of {approval_item.requester}: {action_text}"
                )
                response_body = asyncio.run(invoke_mcp_client(action_text, approval_item.requester))
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
        print(f"result {result}")
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

        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": error_response,
        }


if __name__ == "__main__":
    pprint(lambda_handler(
        {
            "body": (
                '{'
                    '"execution_timeout": 300,'
                    '"request_id": "cde914de3cebb4d18c35fb19231089921c3811766d8abd7b416f478627d92569"'
                '}'
            )
        },
        {},
    ))