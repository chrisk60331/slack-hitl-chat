"""
AgentCore HITL MCP Integration Package.

This package provides Human-in-the-Loop (HITL) capabilities for MCP servers,
enabling approval workflows for high-risk operations.
"""

from .approval_handler import ApprovalItem, ApprovalDecision, get_approval_status
# Removed imports for deleted modules
# from .mcp_server import (
#     ApprovalConfig,
#     HITLServer,
#     MCPRequest,
#     RiskLevel,
#     DefaultRiskEvaluator,
# )
# from .cli import cli

__version__ = "0.1.0"
__all__ = [
    "ApprovalItem",
    "ApprovalDecision", 
    "get_approval_status",
    # Removed exports for deleted modules
    # "ApprovalConfig",
    # "HITLServer",
    # "MCPRequest",
    # "RiskLevel",
    # "DefaultRiskEvaluator",
    # "cli",
] 