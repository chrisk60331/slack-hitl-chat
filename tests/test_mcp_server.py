"""
Unit tests for the MCP server HITL integration.

Tests the HITLServer, risk evaluation, and approval workflow.
"""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, Mock, patch
from typing import Any, Dict

import pytest
from pydantic import ValidationError

from src.mcp_server import (
    ApprovalConfig,
    DefaultRiskEvaluator,
    HITLServer,
    MCPRequest,
    RiskLevel,
)
from src.approval_handler import ApprovalItem


class TestRiskLevel:
    """Test cases for the RiskLevel enum."""

    def test_requires_approval_property(self) -> None:
        """Test the requires_approval property."""
        assert RiskLevel.LOW.requires_approval is False
        assert RiskLevel.MEDIUM.requires_approval is False
        assert RiskLevel.HIGH.requires_approval is True
        assert RiskLevel.CRITICAL.requires_approval is True

    def test_timeout_seconds_property(self) -> None:
        """Test the timeout_seconds property."""
        assert RiskLevel.LOW.timeout_seconds == 900
        assert RiskLevel.MEDIUM.timeout_seconds == 900
        assert RiskLevel.HIGH.timeout_seconds == 1800
        assert RiskLevel.CRITICAL.timeout_seconds == 3600


class TestApprovalConfig:
    """Test cases for the ApprovalConfig model."""

    def test_approval_config_creation(self) -> None:
        """Test ApprovalConfig creation with required fields."""
        config = ApprovalConfig(
            lambda_function_url="https://test.lambda-url.aws.com"
        )
        
        assert config.lambda_function_url == "https://test.lambda-url.aws.com"
        assert config.default_approver == "admin"
        assert config.timeout_seconds == 1800
        assert config.auto_approve_low_risk is True
        assert config.required_approvers == {}

    def test_approval_config_with_custom_values(self) -> None:
        """Test ApprovalConfig with custom values."""
        config = ApprovalConfig(
            lambda_function_url="https://test.lambda-url.aws.com",
            default_approver="security_team",
            timeout_seconds=3600,
            auto_approve_low_risk=False,
            required_approvers={"high_risk": ["admin", "security"]}
        )
        
        assert config.default_approver == "security_team"
        assert config.timeout_seconds == 3600
        assert config.auto_approve_low_risk is False
        assert config.required_approvers == {"high_risk": ["admin", "security"]}

    def test_approval_config_validation_error(self) -> None:
        """Test ApprovalConfig validation error for missing required field."""
        with pytest.raises(ValidationError):
            ApprovalConfig()  # Missing lambda_function_url


class TestMCPRequest:
    """Test cases for the MCPRequest model."""

    def test_mcp_request_creation_with_defaults(self) -> None:
        """Test MCPRequest creation with default values."""
        request = MCPRequest(method="tools/call")
        
        assert isinstance(request.request_id, str)
        assert len(request.request_id) > 0
        assert request.method == "tools/call"
        assert request.params == {}
        assert request.tool_name is None
        assert request.resource_uri is None
        assert request.user_id == "unknown"
        assert isinstance(request.timestamp, str)

    def test_mcp_request_creation_with_values(self) -> None:
        """Test MCPRequest creation with provided values."""
        request = MCPRequest(
            method="tools/call",
            params={"path": "/etc/passwd"},
            tool_name="file_read",
            resource_uri="file:///etc/passwd",
            user_id="test_user"
        )
        
        assert request.method == "tools/call"
        assert request.params == {"path": "/etc/passwd"}
        assert request.tool_name == "file_read"
        assert request.resource_uri == "file:///etc/passwd"
        assert request.user_id == "test_user"

    def test_unique_request_ids(self) -> None:
        """Test that request IDs are unique."""
        request1 = MCPRequest(method="tools/call")
        request2 = MCPRequest(method="tools/call")
        
        assert request1.request_id != request2.request_id


class TestDefaultRiskEvaluator:
    """Test cases for the DefaultRiskEvaluator."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.evaluator = DefaultRiskEvaluator()

    def test_evaluate_low_risk_operations(self) -> None:
        """Test evaluation of low-risk operations."""
        request = MCPRequest(method="tools/list")
        risk = self.evaluator.evaluate_risk(request)
        assert risk == RiskLevel.LOW

        request = MCPRequest(method="resources/list")
        risk = self.evaluator.evaluate_risk(request)
        assert risk == RiskLevel.LOW

    def test_evaluate_high_risk_tools(self) -> None:
        """Test evaluation of high-risk tools."""
        request = MCPRequest(
            method="tools/call",
            tool_name="bash",
            params={"command": "ls -la"}
        )
        risk = self.evaluator.evaluate_risk(request)
        assert risk == RiskLevel.HIGH

        request = MCPRequest(
            method="tools/call",
            tool_name="file_delete",
            params={"path": "/tmp/test.txt"}
        )
        risk = self.evaluator.evaluate_risk(request)
        assert risk == RiskLevel.HIGH

    def test_evaluate_critical_patterns(self) -> None:
        """Test evaluation of critical risk patterns."""
        request = MCPRequest(
            method="tools/call",
            tool_name="bash",
            params={"command": "sudo rm -rf /"}
        )
        risk = self.evaluator.evaluate_risk(request)
        assert risk == RiskLevel.CRITICAL

        request = MCPRequest(
            method="tools/call",
            tool_name="sql_execute",
            params={"query": "DROP TABLE users"}
        )
        risk = self.evaluator.evaluate_risk(request)
        assert risk == RiskLevel.CRITICAL

    def test_evaluate_file_path_risks(self) -> None:
        """Test evaluation based on file paths."""
        # Critical path
        request = MCPRequest(
            method="tools/call",
            tool_name="file_read",
            params={"path": "/etc/passwd"}
        )
        risk = self.evaluator.evaluate_risk(request)
        assert risk == RiskLevel.CRITICAL

        # High-risk deletion
        request = MCPRequest(
            method="tools/call",
            tool_name="file_operation",
            params={"action": "delete", "path": "/home/user/file.txt"}
        )
        risk = self.evaluator.evaluate_risk(request)
        assert risk == RiskLevel.HIGH

    def test_evaluate_network_operations(self) -> None:
        """Test evaluation of network operations."""
        request = MCPRequest(
            method="tools/call",
            tool_name="http_request",
            params={"url": "https://example.com/api"}
        )
        risk = self.evaluator.evaluate_risk(request)
        assert risk == RiskLevel.HIGH

    def test_evaluate_medium_risk_default(self) -> None:
        """Test default medium risk evaluation."""
        request = MCPRequest(
            method="tools/call",
            tool_name="unknown_tool",
            params={"some": "params"}
        )
        risk = self.evaluator.evaluate_risk(request)
        assert risk == RiskLevel.MEDIUM

    def test_caching_behavior(self) -> None:
        """Test that risk evaluation is cached."""
        request = MCPRequest(
            method="tools/call",
            tool_name="test_tool",
            params={"test": "value"}
        )
        
        # First evaluation
        risk1 = self.evaluator.evaluate_risk(request)
        
        # Second evaluation should return cached result
        risk2 = self.evaluator.evaluate_risk(request)
        
        assert risk1 == risk2
        # Verify cache info (lru_cache provides this)
        assert self.evaluator.evaluate_risk.cache_info().hits >= 1


class TestHITLServer:
    """Test cases for the HITLServer."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.config = ApprovalConfig(
            lambda_function_url="https://test.lambda-url.aws.com"
        )
        self.server = HITLServer(self.config)

    def test_hitl_server_initialization(self) -> None:
        """Test HITLServer initialization."""
        assert self.server.config == self.config
        assert isinstance(self.server.risk_evaluator, DefaultRiskEvaluator)
        assert self.server.server.name == "hitl-mcp-server"
        assert self.server.pending_approvals == {}
        assert self.server.approval_cache == {}

    def test_custom_risk_evaluator(self) -> None:
        """Test HITLServer with custom risk evaluator."""
        class CustomEvaluator:
            def evaluate_risk(self, request: MCPRequest) -> RiskLevel:
                return RiskLevel.HIGH
        
        custom_evaluator = CustomEvaluator()
        server = HITLServer(self.config, custom_evaluator)
        
        assert server.risk_evaluator == custom_evaluator

    @patch('src.mcp_server.get_approval_status')
    async def test_handle_approval_status_found(self, mock_get_status: Mock) -> None:
        """Test approval status check for existing request."""
        # Mock approval item
        mock_approval = ApprovalItem(
            request_id="test-123",
            requester="test_user",
            approver="admin",
            approval_status="approve"
        )
        mock_get_status.return_value = mock_approval
        
        result = await self.server._handle_approval_status({"request_id": "test-123"})
        
        assert len(result) == 1
        assert "✅ Request test-123: approve" in result[0].text
        assert "Requester: test_user" in result[0].text
        assert "Approver: admin" in result[0].text

    @patch('src.mcp_server.get_approval_status')
    async def test_handle_approval_status_not_found(self, mock_get_status: Mock) -> None:
        """Test approval status check for non-existent request."""
        mock_get_status.return_value = None
        
        result = await self.server._handle_approval_status({"request_id": "nonexistent"})
        
        assert len(result) == 1
        assert "❌ No approval request found with ID: nonexistent" in result[0].text

    async def test_handle_approval_status_missing_id(self) -> None:
        """Test approval status check without request ID."""
        result = await self.server._handle_approval_status({})
        
        assert len(result) == 1
        assert "❌ Error: request_id is required" in result[0].text

    async def test_handle_list_pending_approvals_empty(self) -> None:
        """Test listing pending approvals when none exist."""
        result = await self.server._handle_list_pending_approvals()
        
        assert len(result) == 1
        assert "No pending approval requests" in result[0].text

    async def test_handle_list_pending_approvals_with_requests(self) -> None:
        """Test listing pending approvals with existing requests."""
        # Add some pending requests
        request1 = MCPRequest(method="tools/call", tool_name="test_tool1", user_id="user1")
        request2 = MCPRequest(method="tools/call", tool_name="test_tool2", user_id="user2")
        
        self.server.pending_approvals[request1.request_id] = request1
        self.server.pending_approvals[request2.request_id] = request2
        
        result = await self.server._handle_list_pending_approvals()
        
        assert len(result) == 1
        assert "Pending approval requests:" in result[0].text
        assert "test_tool1 (user1)" in result[0].text
        assert "test_tool2 (user2)" in result[0].text

    def test_format_proposed_action(self) -> None:
        """Test formatting of proposed actions."""
        request = MCPRequest(
            method="tools/call",
            tool_name="file_delete",
            params={"path": "/tmp/test.txt", "force": True}
        )
        
        action = self.server._format_proposed_action(request)
        
        assert "Execute MCP tools/call with tool 'file_delete'" in action
        assert '"path": "/tmp/test.txt"' in action
        assert '"force": true' in action

    def test_format_proposed_action_large_params(self) -> None:
        """Test formatting with large parameters (truncation)."""
        large_params = {"data": "x" * 1000}  # Large parameter
        request = MCPRequest(
            method="tools/call",
            tool_name="data_process",
            params=large_params
        )
        
        action = self.server._format_proposed_action(request)
        
        assert "Execute MCP tools/call with tool 'data_process'" in action
        assert "..." in action  # Should be truncated

    def test_get_cache_key(self) -> None:
        """Test cache key generation."""
        request1 = MCPRequest(
            method="tools/call",
            tool_name="test_tool",
            params={"static": "value"},
            user_id="user1"
        )
        
        request2 = MCPRequest(
            method="tools/call",
            tool_name="test_tool",
            params={"static": "value"},
            user_id="user2"  # Different user
        )
        
        # Cache keys should be the same (user_id excluded)
        key1 = self.server._get_cache_key(request1)
        key2 = self.server._get_cache_key(request2)
        
        assert key1 == key2
        assert "tools/call" in key1
        assert "test_tool" in key1

    @patch('src.mcp_server.httpx.AsyncClient')
    async def test_send_approval_request_success(self, mock_client_class: Mock) -> None:
        """Test successful approval request sending."""
        # Mock HTTP client
        mock_client = AsyncMock()
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_client.post.return_value = mock_response
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        approval_item = ApprovalItem(
            request_id="test-123",
            requester="test_user",
            proposed_action="Test action"
        )
        
        result = await self.server._send_approval_request(approval_item)
        
        assert result is True
        mock_client.post.assert_called_once()

    @patch('src.mcp_server.httpx.AsyncClient')
    async def test_send_approval_request_failure(self, mock_client_class: Mock) -> None:
        """Test failed approval request sending."""
        # Mock HTTP client with exception
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("HTTP error")
        mock_client_class.return_value.__aenter__.return_value = mock_client
        
        approval_item = ApprovalItem(
            request_id="test-123",
            requester="test_user",
            proposed_action="Test action"
        )
        
        result = await self.server._send_approval_request(approval_item)
        
        assert result is False

    @patch('src.mcp_server.get_approval_status')
    async def test_wait_for_approval_approved(self, mock_get_status: Mock) -> None:
        """Test waiting for approval that gets approved."""
        # Mock immediate approval
        mock_approval = ApprovalItem(
            request_id="test-123",
            approval_status="approve"
        )
        mock_get_status.return_value = mock_approval
        
        result = await self.server._wait_for_approval("test-123", 10)
        
        assert result is True

    @patch('src.mcp_server.get_approval_status')
    async def test_wait_for_approval_rejected(self, mock_get_status: Mock) -> None:
        """Test waiting for approval that gets rejected."""
        # Mock immediate rejection
        mock_approval = ApprovalItem(
            request_id="test-123",
            approval_status="reject"
        )
        mock_get_status.return_value = mock_approval
        
        result = await self.server._wait_for_approval("test-123", 10)
        
        assert result is False

    @patch('src.mcp_server.get_approval_status')
    async def test_wait_for_approval_timeout(self, mock_get_status: Mock) -> None:
        """Test waiting for approval that times out."""
        # Mock pending status (never resolved)
        mock_approval = ApprovalItem(
            request_id="test-123",
            approval_status="pending"
        )
        mock_get_status.return_value = mock_approval
        
        # Use short timeout for test
        result = await self.server._wait_for_approval("test-123", 1)
        
        assert result is False

    @patch('src.mcp_server.get_approval_status')
    async def test_wait_for_approval_not_found(self, mock_get_status: Mock) -> None:
        """Test waiting for approval that doesn't exist."""
        mock_get_status.return_value = None
        
        result = await self.server._wait_for_approval("nonexistent", 1)
        
        assert result is False

    @patch.object(HITLServer, '_send_approval_request')
    @patch.object(HITLServer, '_wait_for_approval')
    async def test_request_approval_success(
        self, 
        mock_wait: AsyncMock, 
        mock_send: AsyncMock
    ) -> None:
        """Test successful approval request flow."""
        mock_send.return_value = True
        mock_wait.return_value = True
        
        request = MCPRequest(
            method="tools/call",
            tool_name="high_risk_tool",
            user_id="test_user"
        )
        
        result = await self.server._request_approval(request, RiskLevel.HIGH)
        
        assert result is True
        mock_send.assert_called_once()
        mock_wait.assert_called_once()
        
        # Check that request was cached
        cache_key = self.server._get_cache_key(request)
        assert self.server.approval_cache[cache_key] is True

    @patch.object(HITLServer, '_send_approval_request')
    async def test_request_approval_send_failure(self, mock_send: AsyncMock) -> None:
        """Test approval request when sending fails."""
        mock_send.return_value = False
        
        request = MCPRequest(
            method="tools/call",
            tool_name="high_risk_tool",
            user_id="test_user"
        )
        
        result = await self.server._request_approval(request, RiskLevel.HIGH)
        
        assert result is False

    async def test_request_approval_cached_result(self) -> None:
        """Test approval request with cached result."""
        request = MCPRequest(
            method="tools/call",
            tool_name="test_tool",
            user_id="test_user"
        )
        
        # Pre-populate cache
        cache_key = self.server._get_cache_key(request)
        self.server.approval_cache[cache_key] = True
        
        result = await self.server._request_approval(request, RiskLevel.HIGH)
        
        assert result is True
        # Should not create pending request since it was cached
        assert request.request_id not in self.server.pending_approvals


class TestIntegration:
    """Integration tests for the complete HITL flow."""

    def setup_method(self) -> None:
        """Set up integration test fixtures."""
        self.config = ApprovalConfig(
            lambda_function_url="https://test.lambda-url.aws.com",
            auto_approve_low_risk=True
        )
        self.server = HITLServer(self.config)

    @patch.object(HITLServer, '_request_approval')
    async def test_full_flow_low_risk_auto_approved(self, mock_request_approval: AsyncMock) -> None:
        """Test full flow for low-risk operation (auto-approved)."""
        # Low-risk operations should not require approval
        mock_request_approval.should_not_be_called = True
        
        # Simulate MCP tool call
        arguments = {"path": "/tmp/safe_file.txt"}
        
        # This would normally go through the MCP server's call_tool handler
        request = MCPRequest(
            method="tools/call",
            tool_name="safe_tool",
            params=arguments,
            user_id="test_user"
        )
        
        risk_level = self.server.risk_evaluator.evaluate_risk(request)
        
        # Should be low risk and not require approval
        assert risk_level == RiskLevel.LOW
        assert not risk_level.requires_approval

    @patch.object(HITLServer, '_request_approval')
    async def test_full_flow_high_risk_requires_approval(self, mock_request_approval: AsyncMock) -> None:
        """Test full flow for high-risk operation requiring approval."""
        mock_request_approval.return_value = True
        
        # Simulate high-risk MCP tool call
        arguments = {"command": "rm -rf /tmp/*"}
        
        request = MCPRequest(
            method="tools/call",
            tool_name="bash",
            params=arguments,
            user_id="test_user"
        )
        
        risk_level = self.server.risk_evaluator.evaluate_risk(request)
        
        # Should be high risk and require approval
        assert risk_level == RiskLevel.HIGH
        assert risk_level.requires_approval
        
        # Simulate approval flow
        if risk_level.requires_approval:
            approval_granted = await self.server._request_approval(request, risk_level)
            assert approval_granted is True
            mock_request_approval.assert_called_once()

    @patch.object(HITLServer, '_request_approval')
    async def test_full_flow_critical_risk_rejected(self, mock_request_approval: AsyncMock) -> None:
        """Test full flow for critical operation that gets rejected."""
        mock_request_approval.return_value = False
        
        # Simulate critical-risk MCP tool call
        arguments = {"query": "DROP TABLE users"}
        
        request = MCPRequest(
            method="tools/call",
            tool_name="sql_execute",
            params=arguments,
            user_id="test_user"
        )
        
        risk_level = self.server.risk_evaluator.evaluate_risk(request)
        
        # Should be critical risk
        assert risk_level == RiskLevel.CRITICAL
        assert risk_level.requires_approval
        
        # Simulate approval flow that gets rejected
        if risk_level.requires_approval:
            approval_granted = await self.server._request_approval(request, risk_level)
            assert approval_granted is False
            mock_request_approval.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__]) 