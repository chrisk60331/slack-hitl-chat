"""
MCP Server with Human-in-the-Loop (HITL) approval integration.

This server acts as a middleware that intercepts all MCP requests,
evaluates if they need approval, and brokers the approval process.
"""

import asyncio
import json
import logging
import uuid
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from typing import Any, Dict, List, Optional, Protocol, Sequence
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, Field

from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

from .approval_handler import ApprovalItem, get_approval_status


logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk levels for operations."""
    
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    
    @property
    def requires_approval(self) -> bool:
        """Whether this risk level requires approval."""
        return self in (RiskLevel.HIGH, RiskLevel.CRITICAL)
    
    @property
    def timeout_seconds(self) -> int:
        """Timeout for approval in seconds."""
        if self == RiskLevel.CRITICAL:
            return 3600  # 1 hour
        elif self == RiskLevel.HIGH:
            return 1800  # 30 minutes
        else:
            return 900   # 15 minutes


class ApprovalConfig(BaseModel):
    """Configuration for approval requirements."""
    
    lambda_function_url: str = Field(..., description="URL of the approval Lambda function")
    default_approver: str = Field(default="admin", description="Default approver ID")
    timeout_seconds: int = Field(default=1800, description="Default timeout for approvals")
    auto_approve_low_risk: bool = Field(default=True, description="Auto-approve low-risk operations")
    required_approvers: Dict[str, List[str]] = Field(default_factory=dict, description="Required approvers by operation type")


class MCPRequest(BaseModel):
    """Represents an MCP request for approval evaluation."""
    
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    method: str
    params: Dict[str, Any] = Field(default_factory=dict)
    tool_name: Optional[str] = None
    resource_uri: Optional[str] = None
    user_id: str = "unknown"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RiskEvaluator(Protocol):
    """Protocol for risk evaluation strategies."""
    
    def evaluate_risk(self, request: MCPRequest) -> RiskLevel:
        """Evaluate the risk level of an MCP request."""
        ...


class DefaultRiskEvaluator:
    """Default risk evaluation strategy."""
    
    # High-risk patterns
    HIGH_RISK_TOOLS = {
        "bash", "shell", "exec", "run_command", 
        "file_delete", "rm", "delete_file",
        "network_request", "http_request", "api_call",
        "database_query", "sql_execute"
    }
    
    CRITICAL_RISK_PATTERNS = {
        "sudo", "rm -rf", "format", "mkfs", 
        "dd if=", "shutdown", "reboot",
        "DROP TABLE", "DELETE FROM", "TRUNCATE"
    }
    
    @lru_cache(maxsize=1000)
    def evaluate_risk(self, request: MCPRequest) -> RiskLevel:
        """
        Evaluate risk level based on tool name and parameters.
        
        Args:
            request: The MCP request to evaluate
            
        Returns:
            Risk level for the request
        """
        # Check for critical patterns first
        if self._contains_critical_patterns(request):
            return RiskLevel.CRITICAL
        
        # Check tool name against high-risk list
        if request.tool_name and request.tool_name.lower() in self.HIGH_RISK_TOOLS:
            return RiskLevel.HIGH
        
        # Check method types
        if request.method in ("tools/call", "resources/read", "resources/write"):
            return self._evaluate_tool_risk(request)
        
        # Default to low risk for read-only operations
        if request.method in ("tools/list", "resources/list", "prompts/list"):
            return RiskLevel.LOW
        
        return RiskLevel.MEDIUM
    
    def _contains_critical_patterns(self, request: MCPRequest) -> bool:
        """Check if request contains critical risk patterns."""
        # Convert request to string for pattern matching
        request_str = json.dumps(request.model_dump()).lower()
        
        return any(pattern.lower() in request_str for pattern in self.CRITICAL_RISK_PATTERNS)
    
    def _evaluate_tool_risk(self, request: MCPRequest) -> RiskLevel:
        """Evaluate risk for tool operations."""
        params = request.params or {}
        
        # File operations
        if "path" in params or "file" in params:
            # Check for dangerous file operations
            for key, value in params.items():
                if isinstance(value, str):
                    if any(pattern in value.lower() for pattern in ["/etc/", "/sys/", "/proc/", "system32"]):
                        return RiskLevel.CRITICAL
                    if any(pattern in value.lower() for pattern in ["delete", "remove", "rm"]):
                        return RiskLevel.HIGH
        
        # Network operations
        if any(key in params for key in ["url", "host", "endpoint"]):
            return RiskLevel.HIGH
        
        return RiskLevel.MEDIUM


class HITLServer:
    """Human-in-the-Loop MCP Server."""
    
    def __init__(self, config: ApprovalConfig, risk_evaluator: Optional[RiskEvaluator] = None):
        self.config = config
        self.risk_evaluator = risk_evaluator or DefaultRiskEvaluator()
        self.server = Server("hitl-mcp-server")
        self.pending_approvals: Dict[str, MCPRequest] = {}
        self.approval_cache: Dict[str, bool] = {}  # Cache recent approvals
        
        # Setup MCP server handlers
        self._setup_handlers()
    
    def _setup_handlers(self) -> None:
        """Setup MCP server request handlers with HITL integration."""
        
        @self.server.list_tools()
        async def handle_list_tools() -> List[types.Tool]:
            """List available tools."""
            return [
                types.Tool(
                    name="approval_status",
                    description="Check the status of a pending approval request",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "request_id": {
                                "type": "string",
                                "description": "The approval request ID"
                            }
                        },
                        "required": ["request_id"]
                    }
                ),
                types.Tool(
                    name="list_pending_approvals",
                    description="List all pending approval requests",
                    inputSchema={"type": "object", "properties": {}}
                )
            ]
        
        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[types.TextContent]:
            """Handle tool calls with HITL approval integration."""
            
            # Create request object
            request = MCPRequest(
                method="tools/call",
                params=arguments,
                tool_name=name,
                user_id=arguments.get("user_id", "unknown")
            )
            
            # Handle special HITL tools directly
            if name == "approval_status":
                return await self._handle_approval_status(arguments)
            elif name == "list_pending_approvals":
                return await self._handle_list_pending_approvals()
            
            # Evaluate risk and check if approval is needed
            risk_level = self.risk_evaluator.evaluate_risk(request)
            
            if risk_level.requires_approval:
                approval_granted = await self._request_approval(request, risk_level)
                if not approval_granted:
                    return [types.TextContent(
                        type="text",
                        text=f"❌ Tool execution denied. Approval request {request.request_id} was rejected or timed out."
                    )]
            
            # If we get here, approval was granted or not required
            # In a real implementation, you'd forward to the actual tool
            return [types.TextContent(
                type="text",
                text=f"✅ Tool '{name}' executed successfully with arguments: {arguments}"
            )]
    
    async def _request_approval(self, request: MCPRequest, risk_level: RiskLevel) -> bool:
        """
        Request approval for a high-risk operation.
        
        Args:
            request: The MCP request requiring approval
            risk_level: The evaluated risk level
            
        Returns:
            True if approval was granted, False otherwise
        """
        try:
            # Check cache first
            cache_key = self._get_cache_key(request)
            if cache_key in self.approval_cache:
                return self.approval_cache[cache_key]
            
            # Create approval request
            approval_item = ApprovalItem(
                request_id=request.request_id,
                requester=request.user_id,
                approver=self.config.default_approver,
                agent_prompt=f"MCP {request.method} operation",
                proposed_action=self._format_proposed_action(request),
                reason=f"Risk level: {risk_level.value}",
                approval_status="pending"
            )
            
            # Send to approval Lambda
            approval_sent = await self._send_approval_request(approval_item)
            if not approval_sent:
                logger.error(f"Failed to send approval request {request.request_id}")
                return False
            
            # Store pending request
            self.pending_approvals[request.request_id] = request
            
            # Wait for approval with timeout
            timeout = risk_level.timeout_seconds
            approval_granted = await self._wait_for_approval(request.request_id, timeout)
            
            # Cache the result
            self.approval_cache[cache_key] = approval_granted
            
            # Clean up
            self.pending_approvals.pop(request.request_id, None)
            
            return approval_granted
            
        except Exception as e:
            logger.error(f"Error in approval process: {e}")
            return False
    
    async def _send_approval_request(self, approval_item: ApprovalItem) -> bool:
        """Send approval request to Lambda function."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.config.lambda_function_url,
                    json=approval_item.model_dump(),
                    timeout=30.0
                )
                response.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"Failed to send approval request: {e}")
            return False
    
    async def _wait_for_approval(self, request_id: str, timeout_seconds: int) -> bool:
        """
        Wait for approval decision with polling.
        
        Args:
            request_id: The request ID to check
            timeout_seconds: How long to wait
            
        Returns:
            True if approved, False if rejected or timeout
        """
        start_time = asyncio.get_event_loop().time()
        poll_interval = 5  # Poll every 5 seconds
        
        while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
            try:
                # Check approval status
                approval_item = get_approval_status(request_id)
                if approval_item:
                    if approval_item.approval_status == "approve":
                        return True
                    elif approval_item.approval_status == "reject":
                        return False
                
                # Wait before polling again
                await asyncio.sleep(poll_interval)
                
            except Exception as e:
                logger.error(f"Error checking approval status: {e}")
                await asyncio.sleep(poll_interval)
        
        # Timeout reached
        logger.warning(f"Approval request {request_id} timed out after {timeout_seconds} seconds")
        return False
    
    async def _handle_approval_status(self, arguments: Dict[str, Any]) -> List[types.TextContent]:
        """Handle approval status check."""
        request_id = arguments.get("request_id")
        if not request_id:
            return [types.TextContent(
                type="text",
                text="❌ Error: request_id is required"
            )]
        
        try:
            approval_item = get_approval_status(request_id)
            if not approval_item:
                return [types.TextContent(
                    type="text",
                    text=f"❌ No approval request found with ID: {request_id}"
                )]
            
            status_emoji = {
                "pending": "⏳",
                "approve": "✅", 
                "reject": "❌"
            }.get(approval_item.approval_status, "❓")
            
            return [types.TextContent(
                type="text",
                text=f"{status_emoji} Request {request_id}: {approval_item.approval_status}\n"
                     f"Requester: {approval_item.requester}\n"
                     f"Approver: {approval_item.approver}\n"
                     f"Timestamp: {approval_item.timestamp}"
            )]
            
        except Exception as e:
            return [types.TextContent(
                type="text",
                text=f"❌ Error checking approval status: {str(e)}"
            )]
    
    async def _handle_list_pending_approvals(self) -> List[types.TextContent]:
        """Handle listing pending approvals."""
        if not self.pending_approvals:
            return [types.TextContent(
                type="text",
                text="No pending approval requests"
            )]
        
        pending_list = []
        for request_id, request in self.pending_approvals.items():
            pending_list.append(
                f"• {request_id}: {request.tool_name} ({request.user_id}) - {request.timestamp}"
            )
        
        return [types.TextContent(
            type="text",
            text="Pending approval requests:\n" + "\n".join(pending_list)
        )]
    
    def _format_proposed_action(self, request: MCPRequest) -> str:
        """Format the proposed action for human review."""
        action = f"Execute MCP {request.method}"
        if request.tool_name:
            action += f" with tool '{request.tool_name}'"
        
        if request.params:
            # Truncate large params for readability
            params_str = json.dumps(request.params, indent=2)
            if len(params_str) > 500:
                params_str = params_str[:500] + "..."
            action += f"\n\nParameters:\n{params_str}"
        
        return action
    
    @lru_cache(maxsize=1000)
    def _get_cache_key(self, request: MCPRequest) -> str:
        """Generate cache key for approval requests."""
        # Create cache key based on method, tool, and key parameters
        key_parts = [request.method]
        if request.tool_name:
            key_parts.append(request.tool_name)
        
        # Include relevant parameters in cache key
        if request.params:
            # Sort and include only non-variable parameters
            static_params = {
                k: v for k, v in request.params.items() 
                if k not in ["user_id", "timestamp", "request_id"]
            }
            key_parts.append(json.dumps(static_params, sort_keys=True))
        
        return ":".join(key_parts)
    
    async def serve(self) -> None:
        """Start the MCP server."""
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="hitl-mcp-server",
                    server_version="1.0.0",
                    capabilities=self.server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={}
                    )
                )
            )


async def main() -> None:
    """Main entry point for the HITL MCP server."""
    import os
    
    # Load configuration from environment
    config = ApprovalConfig(
        lambda_function_url=os.environ.get("LAMBDA_FUNCTION_URL", ""),
        default_approver=os.environ.get("DEFAULT_APPROVER", "admin"),
        timeout_seconds=int(os.environ.get("APPROVAL_TIMEOUT", "1800")),
        auto_approve_low_risk=os.environ.get("AUTO_APPROVE_LOW_RISK", "true").lower() == "true"
    )
    
    # Create and start server
    hitl_server = HITLServer(config)
    await hitl_server.serve()


if __name__ == "__main__":
    asyncio.run(main()) 