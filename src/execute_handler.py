"""
AWS Lambda function for executing approved MCP actions.

This function loads an MCP server and executes approved actions
based on the approval request ID.
"""

import json
import os
import sys
import asyncio
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3
from pydantic import BaseModel, Field

from src.approval_handler import get_approval_status
from src.mcp_client import MCPClient

logger = logging.getLogger(__name__)
# Set up more detailed logging for debugging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Also enable debug logging for related libraries
logging.getLogger('pydantic_ai').setLevel(logging.DEBUG)
logging.getLogger('asyncio').setLevel(logging.DEBUG)

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb', region_name=os.environ['AWS_REGION'])
TABLE_NAME = os.environ['TABLE_NAME']
table = dynamodb.Table(TABLE_NAME)


class ExecutionRequest(BaseModel):
    """Pydantic model for execution requests."""
    request_id: Optional[str] = Field(None, description="Request ID to look up action from DynamoDB")
    action_text: Optional[str] = Field(None, description="The natural language action to execute")
    execution_timeout: int = Field(default=300, description="Timeout for execution in seconds")


class ExecutionResult(BaseModel):
    """Pydantic model for execution results."""
    request_id: str
    execution_status: str  # "success", "failed", "timeout"
    result: Any = None
    error_message: Optional[str] = None
    execution_time: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


async def invoke_mcp_client(action_text: str):
    client = MCPClient()
    try:
        await client.connect_to_server("google_mcp/google_admin/mcp_server.py")
        result = await client.process_query(action_text)
    finally:
        await client.cleanup()
    return result


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for executing MCP actions from natural language text.
    
    Args:
        event: Lambda event containing execution request with action_text
        context: Lambda context object
        
    Returns:
        Response dictionary with execution results
    """
    try:
        logger.info(f"Execute Lambda received event: {json.dumps(event, default=str)}")

        # Extract request data from event
        if 'body' in event:
            if isinstance(event['body'], str):
                body = json.loads(event['body'])
            else:
                body = event['body']
        else:
            body = event
        
        logger.debug(f"Parsed request body: {body}")
        
        # Create execution request
        execution_request = ExecutionRequest(**body)
        logger.debug(f"Created execution request: {execution_request}")
        
        if execution_request.request_id:
            logger.debug(f"Looking up action from DynamoDB for request_id: {execution_request.request_id}")
            # Look up the proposed_action from DynamoDB using request_id
            approval_item = get_approval_status(execution_request.request_id)

            response_body = ""
            if not approval_item:
                raise ValueError(f"Request ID {execution_request.request_id} not found in approval log")
            if approval_item.approval_status != "approve":
                raise ValueError(f"Request {execution_request.request_id} is not approved (status: {approval_item.approval_status})")
            elif approval_item.approval_status == "approve":
                action_text = approval_item.proposed_action
                request_id = execution_request.request_id or "direct_execution"
                logger.info(f"Executing action for request {request_id}: {action_text}")
                response_body = asyncio.run(invoke_mcp_client(action_text))
            action_text = approval_item.proposed_action
            request_id = execution_request.request_id
            logger.debug(f"Retrieved action from DynamoDB: {action_text}")
            
        else:
            raise ValueError("Either action_text or request_id must be provided")
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': response_body
        }
        
    except Exception as e:
        logger.error(f"Lambda execution failed: {e}")
        logger.error(f"Lambda exception type: {type(e)}")
        logger.error(f"Lambda exception traceback: {traceback.format_exc()}")
        
        error_response = {
            'error': 'execution failed',
            'details': str(e),
            'exception_type': str(type(e))
        }
        
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': error_response
        }