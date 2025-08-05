"""
Tests for the execute handler Lambda function.
"""

import json
import pytest
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timezone

from src.execute_handler import (
    lambda_handler,
    ExecutionRequest,
    ExecutionResult,
    parse_proposed_action,
    execute_approved_action,
    load_mcp_server,
    execute_mcp_action
)


class TestExecuteHandler:
    """Test cases for the execute handler."""
    
    def test_execution_request_model(self) -> None:
        """Test ExecutionRequest pydantic model."""
        request = ExecutionRequest(request_id="test-123")
        assert request.request_id == "test-123"
        assert request.execution_timeout == 300  # default
        
        request_with_timeout = ExecutionRequest(
            request_id="test-456", 
            execution_timeout=600
        )
        assert request_with_timeout.execution_timeout == 600
    
    def test_execution_result_model(self) -> None:
        """Test ExecutionResult pydantic model."""
        result = ExecutionResult(
            request_id="test-123",
            execution_status="success",
            result={"message": "User created successfully"}
        )
        assert result.request_id == "test-123"
        assert result.execution_status == "success"
        assert result.result == {"message": "User created successfully"}
        assert result.error_message is None
        
        # Test with error
        error_result = ExecutionResult(
            request_id="test-456",
            execution_status="failed",
            error_message="Tool not found"
        )
        assert error_result.execution_status == "failed"
        assert error_result.error_message == "Tool not found"
    
    def test_parse_proposed_action_valid(self) -> None:
        """Test parsing a valid proposed action."""
        proposed_action = """Execute MCP tools/call with tool 'add_user'

Parameters:
{
  "primary_email": "test@example.com",
  "first_name": "Test",
  "last_name": "User"
}"""
        
        tool_name, parameters = parse_proposed_action(proposed_action)
        assert tool_name == "add_user"
        assert parameters == {
            "primary_email": "test@example.com",
            "first_name": "Test",
            "last_name": "User"
        }
    
    def test_parse_proposed_action_no_parameters(self) -> None:
        """Test parsing proposed action without parameters."""
        proposed_action = "Execute MCP tools/call with tool 'list_users'"
        
        tool_name, parameters = parse_proposed_action(proposed_action)
        assert tool_name == "list_users"
        assert parameters == {}
    
    def test_parse_proposed_action_invalid_format(self) -> None:
        """Test parsing invalid proposed action format."""
        proposed_action = "Invalid format"
        
        with pytest.raises(ValueError, match="Could not extract tool name"):
            parse_proposed_action(proposed_action)
    
    @patch('src.execute_handler.get_approval_status')
    async def test_execute_approved_action_not_found(self, mock_get_approval: Mock) -> None:
        """Test execute_approved_action when request not found."""
        mock_get_approval.return_value = None
        
        result = await execute_approved_action("non-existent-id")
        assert result.execution_status == "failed"
        assert "not found" in result.error_message
    
    @patch('src.execute_handler.get_approval_status')
    async def test_execute_approved_action_not_approved(self, mock_get_approval: Mock) -> None:
        """Test execute_approved_action when request not approved."""
        from src.approval_handler import ApprovalItem
        
        mock_approval = ApprovalItem(
            request_id="test-123",
            approval_status="pending"
        )
        mock_get_approval.return_value = mock_approval
        
        result = await execute_approved_action("test-123")
        assert result.execution_status == "failed"
        assert "not approved" in result.error_message
    
    @patch('src.execute_handler.table')
    @patch('src.execute_handler.execute_mcp_action')
    @patch('src.execute_handler.load_mcp_server')
    @patch('src.execute_handler.get_approval_status')
    async def test_execute_approved_action_success(
        self, 
        mock_get_approval: Mock,
        mock_load_server: AsyncMock,
        mock_execute_action: AsyncMock,
        mock_table: Mock
    ) -> None:
        """Test successful execution of approved action."""
        from src.approval_handler import ApprovalItem
        
        # Mock approval item
        mock_approval = ApprovalItem(
            request_id="test-123",
            approval_status="approve",
            proposed_action="Execute MCP tools/call with tool 'add_user'\n\nParameters:\n{\"primary_email\": \"test@example.com\"}"
        )
        mock_get_approval.return_value = mock_approval
        
        # Mock MCP server and execution
        mock_server = Mock()
        mock_load_server.return_value = mock_server
        mock_execute_action.return_value = {"message": "User created successfully"}
        
        result = await execute_approved_action("test-123")
        
        assert result.execution_status == "success"
        assert result.result == {"message": "User created successfully"}
        
        # Verify DynamoDB update was called
        mock_table.put_item.assert_called_once()
    
    @patch('src.execute_handler.asyncio.wait_for')
    @patch('src.execute_handler.load_mcp_server')
    @patch('src.execute_handler.get_approval_status')
    async def test_execute_approved_action_timeout(
        self,
        mock_get_approval: Mock,
        mock_load_server: AsyncMock,
        mock_wait_for: AsyncMock
    ) -> None:
        """Test execution timeout."""
        from src.approval_handler import ApprovalItem
        import asyncio
        
        mock_approval = ApprovalItem(
            request_id="test-123",
            approval_status="approve",
            proposed_action="Execute MCP tools/call with tool 'add_user'"
        )
        mock_get_approval.return_value = mock_approval
        mock_load_server.return_value = Mock()
        mock_wait_for.side_effect = asyncio.TimeoutError()
        
        result = await execute_approved_action("test-123", timeout_seconds=5)
        
        assert result.execution_status == "timeout"
        assert "timed out" in result.error_message
    
    @patch.dict('os.environ', {'TABLE_NAME': 'test-table'})
    @patch('src.execute_handler.execute_approved_action')
    def test_lambda_handler_success(self, mock_execute: AsyncMock) -> None:
        """Test successful lambda handler execution."""
        # Mock execution result
        mock_result = ExecutionResult(
            request_id="test-123",
            execution_status="success",
            result={"message": "Success"}
        )
        mock_execute.return_value = mock_result
        
        event = {
            "body": {
                "request_id": "test-123",
                "execution_timeout": 300
            }
        }
        
        response = lambda_handler(event, Mock())
        
        assert response["statusCode"] == 200
        assert response["body"]["execution_status"] == "success"
    
    @patch.dict('os.environ', {'TABLE_NAME': 'test-table'})
    def test_lambda_handler_invalid_request(self) -> None:
        """Test lambda handler with invalid request."""
        event = {
            "body": {
                # Missing required request_id
                "execution_timeout": 300
            }
        }
        
        response = lambda_handler(event, Mock())
        
        assert response["statusCode"] == 500
        assert "error" in response["body"]
    
    @patch.dict('os.environ', {'TABLE_NAME': 'test-table'})
    @patch('src.execute_handler.execute_approved_action')
    def test_lambda_handler_string_body(self, mock_execute: AsyncMock) -> None:
        """Test lambda handler with JSON string body."""
        mock_result = ExecutionResult(
            request_id="test-123",
            execution_status="success"
        )
        mock_execute.return_value = mock_result
        
        event = {
            "body": json.dumps({
                "request_id": "test-123"
            })
        }
        
        response = lambda_handler(event, Mock())
        
        assert response["statusCode"] == 200
    
    async def test_load_mcp_server_import_error(self) -> None:
        """Test load_mcp_server with import error."""
        with patch('src.execute_handler.__import__', side_effect=ImportError("Module not found")):
            with pytest.raises(ImportError):
                await load_mcp_server()
    
    async def test_execute_mcp_action_tool_not_found(self) -> None:
        """Test execute_mcp_action when tool not found."""
        mock_server = Mock()
        mock_server.list_tools.return_value = []  # No tools available
        
        with pytest.raises(ValueError, match="Tool 'nonexistent' not found"):
            await execute_mcp_action(mock_server, "nonexistent", {})
    
    async def test_execute_mcp_action_unknown_tool(self) -> None:
        """Test execute_mcp_action with unknown tool type."""
        mock_tool = Mock()
        mock_tool.name = "unknown_tool"
        mock_tool.function = Mock()
        
        mock_server = Mock()
        mock_server.list_tools.return_value = [mock_tool]
        
        with pytest.raises(ValueError, match="Unknown tool: unknown_tool"):
            await execute_mcp_action(mock_server, "unknown_tool", {})


if __name__ == "__main__":
    pytest.main([__file__])