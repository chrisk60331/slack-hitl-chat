"""TOTP MCP package.

Provides a minimal MCP server that can fetch a TOTP secret from AWS Secrets
Manager and return the current TOTP code.
"""

__all__ = [
    "mcp_server",
]
