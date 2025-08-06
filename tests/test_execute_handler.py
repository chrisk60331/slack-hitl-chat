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
    execute_action_from_text,
    create_ai_agent,
    execute_mcp_action
)


class TestExecuteHandler:
    """Test cases for the execute handler."""
    
    def test_execution_request_model(self) -> None:
        """Test ExecutionRequest pydantic model."""
        # Test with action_text
        request = ExecutionRequest(action_text="Create a new user with email test@example.com")
        assert request.action_text == "Create a new user with email test@example.com"
        assert request.execution_timeout == 300  # default
        
        request_with_timeout = ExecutionRequest(
            action_text="List all users in domain example.com", 
            execution_timeout=600
        )
        assert request_with_timeout.execution_timeout == 600
        
        # Test with request_id (for DynamoDB lookup)
        request_with_id = ExecutionRequest(request_id="test-request-123")
        assert request_with_id.request_id == "test-request-123"
        assert request_with_id.action_text is None
        assert request_with_id.execution_timeout == 300
    
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
    
    @patch.dict('os.environ', {
        'MCP_AUTH_TOKEN': 'test-token',
        'AWS_REGION': 'us-east-1',
        'BEDROCK_MODEL_ID': 'anthropic.claude-3-5-haiku-20241022-v1:0'
    })
    async def test_create_ai_agent_success(self) -> None:
        """Test successful AI agent creation."""
        with patch('src.execute_handler.MCPServerStreamableHTTP') as mock_server, \
             patch('src.execute_handler.BedrockConverseModel') as mock_model, \
             patch('src.execute_handler.Agent') as mock_agent:
            
            agent = await create_ai_agent()
            assert agent is not None
            mock_server.assert_called_once()
            mock_model.assert_called_once()
            mock_agent.assert_called_once()
    
    async def test_create_ai_agent_missing_token(self) -> None:
        """Test AI agent creation with missing MCP token."""
        with pytest.raises(ValueError, match="MCP_AUTH_TOKEN environment variable is required"):
            await create_ai_agent()
    
    @patch.dict('os.environ', {'MCP_AUTH_TOKEN': 'test-token'})
    async def test_create_ai_agent_with_defaults(self) -> None:
        """Test AI agent creation with default AWS region and Bedrock model."""
        with patch('src.execute_handler.MCPServerStreamableHTTP') as mock_server, \
             patch('src.execute_handler.BedrockConverseModel') as mock_model, \
             patch('src.execute_handler.Agent') as mock_agent:
            
            agent = await create_ai_agent()
            assert agent is not None
            mock_model.assert_called_once_with(
                model_name='anthropic.claude-3-5-haiku-20241022-v1:0',
                provider='bedrock'
            )
    
    async def test_execute_mcp_action_success(self) -> None:
        """Test successful MCP action execution."""
        mock_agent = AsyncMock()
        mock_result = Mock()
        mock_result.data = {"message": "User created successfully"}
        mock_agent.run.return_value = mock_result
        
        result = await execute_mcp_action(mock_agent, "Create user test@example.com")
        
        assert result == {"message": "User created successfully"}
        mock_agent.run.assert_called_once_with("Create user test@example.com")
    
    async def test_execute_mcp_action_failure(self) -> None:
        """Test MCP action execution failure."""
        mock_agent = AsyncMock()
        mock_agent.run.side_effect = Exception("AI agent error")
        
        with pytest.raises(Exception, match="AI agent error"):
            await execute_mcp_action(mock_agent, "Invalid action")
    
    @patch('src.execute_handler.execute_mcp_action')
    @patch('src.execute_handler.create_ai_agent')
    async def test_execute_action_from_text_success(
        self, 
        mock_create_agent: AsyncMock,
        mock_execute_action: AsyncMock
    ) -> None:
        """Test successful execution of action from text."""
        # Mock AI agent and execution
        mock_agent = Mock()
        mock_create_agent.return_value = mock_agent
        mock_execute_action.return_value = {"message": "User created successfully"}
        
        result = await execute_action_from_text("Create user test@example.com")
        
        assert result.execution_status == "success"
        assert result.result == {"message": "User created successfully"}
        assert result.request_id == "direct_execution"
        
        mock_create_agent.assert_called_once()
        mock_execute_action.assert_called_once_with(mock_agent, "Create user test@example.com")
    
    @patch('src.execute_handler.asyncio.wait_for')
    @patch('src.execute_handler.create_ai_agent')
    async def test_execute_action_from_text_timeout(
        self,
        mock_create_agent: AsyncMock,
        mock_wait_for: AsyncMock
    ) -> None:
        """Test execution timeout."""
        import asyncio
        
        mock_create_agent.return_value = Mock()
        mock_wait_for.side_effect = asyncio.TimeoutError()
        
        result = await execute_action_from_text("Create user test@example.com", timeout_seconds=5)
        
        assert result.execution_status == "timeout"
        assert "timed out" in result.error_message
    
    @patch('src.execute_handler.execute_action_from_text')
    def test_lambda_handler_success(self, mock_execute: AsyncMock) -> None:
        """Test successful lambda handler execution."""
        # Mock execution result
        mock_result = ExecutionResult(
            request_id="direct_execution",
            execution_status="success",
            result={"message": "Success"}
        )
        mock_execute.return_value = mock_result
        
        event = {
            "body": {
                "action_text": "Create user test@example.com",
                "execution_timeout": 300
            }
        }
        
        response = lambda_handler(event, Mock())
        
        assert response["statusCode"] == 200
        assert response["body"]["execution_status"] == "success"
    
    def test_lambda_handler_invalid_request(self) -> None:
        """Test lambda handler with invalid request."""
        event = {
            "body": {
                # Missing required action_text
                "execution_timeout": 300
            }
        }
        
        response = lambda_handler(event, Mock())
        
        assert response["statusCode"] == 500
        assert "error" in response["body"]
    
    @patch('src.execute_handler.execute_action_from_text')
    def test_lambda_handler_string_body(self, mock_execute: AsyncMock) -> None:
        """Test lambda handler with JSON string body."""
        mock_result = ExecutionResult(
            request_id="direct_execution",
            execution_status="success"
        )
        mock_execute.return_value = mock_result
        
        event = {
            "body": json.dumps({
                "action_text": "List all users"
            })
        }
        
        response = lambda_handler(event, Mock())
        
        assert response["statusCode"] == 200
    
    @patch('src.execute_handler.get_approval_status')
    @patch('src.execute_handler.execute_action_from_text')
    def test_lambda_handler_with_request_id_lookup(self, mock_execute: AsyncMock, mock_get_approval: Mock) -> None:
        """Test lambda handler with request_id to lookup action from DynamoDB."""
        from src.approval_handler import ApprovalItem
        
        # Mock approval item from DynamoDB
        mock_approval = ApprovalItem(
            request_id="test-request-123",
            proposed_action="Create a new user with email test@example.com",
            approval_status="approve"
        )
        mock_get_approval.return_value = mock_approval
        
        mock_result = ExecutionResult(
            request_id="test-request-123",
            execution_status="success"
        )
        mock_execute.return_value = mock_result
        
        event = {
            "request_id": "test-request-123",
            "execution_timeout": 300
        }
        
        response = lambda_handler(event, Mock())
        
        assert response["statusCode"] == 200
        mock_get_approval.assert_called_once_with("test-request-123")
        mock_execute.assert_called_once_with(
            "Create a new user with email test@example.com", 
            300, 
            "test-request-123"
        )
    
    @patch('src.execute_handler.get_approval_status')
    def test_lambda_handler_request_id_not_found(self, mock_get_approval: Mock) -> None:
        """Test lambda handler when request_id is not found in DynamoDB."""
        mock_get_approval.return_value = None
        
        event = {
            "request_id": "nonexistent-request"
        }
        
        response = lambda_handler(event, Mock())
        
        assert response["statusCode"] == 500
        assert "not found in approval log" in response["body"]["details"]
    
    @patch('src.execute_handler.get_approval_status')
    def test_lambda_handler_request_not_approved(self, mock_get_approval: Mock) -> None:
        """Test lambda handler when request is not approved."""
        from src.approval_handler import ApprovalItem
        
        mock_approval = ApprovalItem(
            request_id="test-request-123",
            proposed_action="Create a new user",
            approval_status="reject"
        )
        mock_get_approval.return_value = mock_approval
        
        event = {
            "request_id": "test-request-123"
        }
        
        response = lambda_handler(event, Mock())
        
        assert response["statusCode"] == 500
        assert "is not approved" in response["body"]["details"]
    
    def test_lambda_handler_no_action_or_request_id(self) -> None:
        """Test lambda handler when neither action_text nor request_id is provided."""
        event = {
            "execution_timeout": 300
        }
        
        response = lambda_handler(event, Mock())
        
        assert response["statusCode"] == 500
        assert "Either action_text or request_id must be provided" in response["body"]["details"]

    @patch.dict('os.environ', {'MCP_AUTH_TOKEN': 'test-token'})
    async def test_create_ai_agent_runtime_error(self) -> None:
        """Test AI agent creation with runtime error."""
        with patch('src.execute_handler.MCPServerStreamableHTTP', side_effect=Exception("Connection failed")):
            with pytest.raises(RuntimeError, match="AI agent creation failed"):
                await create_ai_agent()


if __name__ == "__main__":
    pytest.main([__file__])