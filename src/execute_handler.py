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
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field

# Add the google_mcp path to the Python path for imports
sys.path.append('/opt/google_mcp')

from src.approval_handler import ApprovalItem, get_approval_status


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
TABLE_NAME = os.environ['TABLE_NAME']
table = dynamodb.Table(TABLE_NAME)


class ExecutionRequest(BaseModel):
    """Pydantic model for execution requests."""
    request_id: str = Field(..., description="The approval request ID to execute")
    execution_timeout: int = Field(default=300, description="Timeout for execution in seconds")


class ExecutionResult(BaseModel):
    """Pydantic model for execution results."""
    request_id: str
    execution_status: str  # "success", "failed", "timeout"
    result: Any = None
    error_message: Optional[str] = None
    execution_time: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


async def load_mcp_server() -> Any:
    """
    Load and initialize the Google MCP server.
    
    Returns:
        Dictionary containing the available MCP tools
    """
    try:
        # Import the Google MCP tool functions directly
        from google_mcp.google_admin.mcp_server import (
            list_users, add_user, get_user, suspend_user, unsuspend_user, 
            get_amazon_roles, add_amazon_role, remove_amazon_role
        )
        from google_mcp.google_admin.services import UserService
        
        # Import the actual MCP server
        from google_mcp.google_admin.mcp_server import mcp
        
        logger.info("Successfully loaded Google MCP tools")
        return mcp
        
    except ImportError as e:
        logger.error(f"Failed to import Google MCP tools: {e}")
        raise RuntimeError(f"Google MCP tools are required but could not be imported: {e}")
        
    except Exception as e:
        logger.error(f"Failed to initialize Google MCP tools: {e}")
        raise RuntimeError(f"Google MCP tools failed to initialize: {e}")


async def execute_mcp_action(mcp_server: Any, tool_name: str, parameters: Dict[str, Any]) -> Any:
    """
    Execute an MCP action using the loaded server.
    
    Args:
        mcp_server: The MCP server instance
        tool_name: Name of the tool to execute
        parameters: Parameters for the tool execution
        
    Returns:
        Result of the tool execution
    """
    try:
        # Get the tool function from the MCP server
        tools = await mcp_server.get_tools()
        if tool_name not in tools:
            raise ValueError(f"Tool '{tool_name}' not found in MCP server")
        
        # Create the appropriate request object based on tool name
        logger.info(f"Executing tool '{tool_name}' with parameters: {parameters}")
        
        if tool_name == "list_users":
            from google_mcp.google_admin.models import ListUsersRequest
            request = ListUsersRequest(**parameters)
        elif tool_name == "add_user":
            from google_mcp.google_admin.models import AddUserRequest
            request = AddUserRequest(**parameters)
        elif tool_name in ["get_user", "suspend_user", "unsuspend_user", "get_amazon_roles"]:
            from google_mcp.google_admin.models import UserKeyRequest
            request = UserKeyRequest(**parameters)
        elif tool_name == "add_amazon_role":
            from google_mcp.google_admin.models import AddRoleRequest
            request = AddRoleRequest(**parameters)
        elif tool_name == "remove_amazon_role":
            from google_mcp.google_admin.models import RemoveRoleRequest
            request = RemoveRoleRequest(**parameters)
        else:
            raise ValueError(f"Unknown tool: {tool_name}")
        
        # Execute the tool using the tool from get_tools
        tool = tools[tool_name]
        
        logger.info(f"Calling tool function with request: {request}")
        result = tool.fn(request)
        logger.debug(f"Tool execution result: {result}")
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to execute MCP action '{tool_name}': {e}")
        raise


def parse_proposed_action(proposed_action: str) -> tuple[str, Dict[str, Any]]:
    """
    Parse the proposed action to extract tool name and parameters.
    
    Args:
        proposed_action: The proposed action string from the approval request
        
    Returns:
        Tuple of (tool_name, parameters)
    """
    try:
        # The proposed_action should contain tool name and parameters
        # Format: "Execute MCP tools/call with tool 'tool_name'\n\nParameters:\n{json}"
        lines = proposed_action.split('\n')
        
        # Extract tool name from the first line
        tool_line = next((line for line in lines if "with tool" in line), "")
        if tool_line:
            # Extract tool name from: "Execute MCP tools/call with tool 'tool_name'"
            tool_name = tool_line.split("'")[1] if "'" in tool_line else ""
        else:
            raise ValueError("Could not extract tool name from proposed action")
        
        # Extract parameters from the JSON part
        json_start = proposed_action.find('Parameters:\n')
        if json_start == -1:
            parameters = {}
        else:
            json_part = proposed_action[json_start + len('Parameters:\n'):].strip()
            if json_part:
                parameters = json.loads(json_part)
            else:
                parameters = {}
        
        logger.info(f"Parsed action - Tool: {tool_name}, Parameters: {parameters}")
        return tool_name, parameters
        
    except Exception as e:
        logger.error(f"Failed to parse proposed action: {e}")
        raise ValueError(f"Invalid proposed action format: {str(e)}")


async def execute_approved_action(request_id: str, timeout_seconds: int = 300) -> ExecutionResult:
    """
    Execute an approved action based on the request ID.
    
    Args:
        request_id: The approval request ID
        timeout_seconds: Timeout for execution
        
    Returns:
        ExecutionResult with the outcome
    """
    try:
        # Get the approval item from DynamoDB
        approval_item = get_approval_status(request_id)
        if not approval_item:
            raise ValueError(f"Approval request {request_id} not found")
        
        if approval_item.approval_status != "approve":
            logging.warning(f"Request {request_id} is not approved. Status: {approval_item.approval_status}")

        # Parse the proposed action to get tool name and parameters
        tool_name, parameters = parse_proposed_action(approval_item.proposed_action)
        
        # Load the MCP server
        mcp_server = await load_mcp_server()
        
        # Execute the action with timeout
        result = await asyncio.wait_for(
            execute_mcp_action(mcp_server, tool_name, parameters),
            timeout=timeout_seconds
        )
        
        # Update the approval item with execution status
        approval_item.approval_status = "executed"
        approval_item.timestamp = datetime.now(timezone.utc).isoformat()
        table.put_item(Item=approval_item.to_dynamodb_item())
        
        return ExecutionResult(
            request_id=request_id,
            execution_status="success",
            result=result
        )
        
    except asyncio.TimeoutError:
        logger.error(f"Execution timeout for request {request_id}")
        return ExecutionResult(
            request_id=request_id,
            execution_status="timeout",
            error_message=f"Execution timed out after {timeout_seconds} seconds"
        )
    except Exception as e:
        logger.error(f"Execution failed for request {request_id}: {e}")
        return ExecutionResult(
            request_id=request_id,
            execution_status="failed",
            error_message=str(e)
        )


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for executing approved MCP actions.
    
    Args:
        event: Lambda event containing execution request
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
        
        # Create execution request
        execution_request = ExecutionRequest(**body)
        
        # Execute the approved action
        # Handle asyncio event loop properly
        try:
            # Check if there's already an event loop running
            asyncio.get_running_loop()
            # If we're in an async context, use a thread pool
            import concurrent.futures
            import threading
            
            def run_in_thread():
                # Create new event loop in thread
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(
                        execute_approved_action(
                            execution_request.request_id, 
                            execution_request.execution_timeout
                        )
                    )
                finally:
                    new_loop.close()
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_thread)
                result = future.result()
                
        except RuntimeError:
            # No event loop running, can use asyncio.run
            result = asyncio.run(
                execute_approved_action(
                    execution_request.request_id, 
                    execution_request.execution_timeout
                )
            )
        
        logger.info(f"Execution completed for request {execution_request.request_id}: {result.execution_status}")
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': result.model_dump()
        }
        
    except Exception as e:
        error_response = {
            'error': 'execution failed',
            'details': str(e)
        }
        logger.error(f"Lambda execution failed: {e}")
        
        return {
            'statusCode': 500,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': error_response
        }