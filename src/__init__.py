"""
AgentCore HITL MCP Integration Package.

This package provides Human-in-the-Loop (HITL) capabilities for MCP servers,
enabling approval workflows for high-risk operations.
"""

from __future__ import annotations

from dotenv import load_dotenv

# Load local env vars when present. Keep imports lightweight to avoid side-effects
# during package import in environments like AWS Lambda or unit tests.
load_dotenv()

__version__ = "0.1.0"
__all__: list[str] = []
