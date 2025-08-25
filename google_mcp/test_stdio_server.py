#!/usr/bin/env python3
"""Simple MCP server for testing stdio transport."""

from fastmcp import FastMCP

# Create a simple MCP server without complex dependencies
mcp = FastMCP("Test Google Admin MCP Server")


@mcp.tool(
    name="test_connection",
    description="Test if the MCP server is working with stdio transport",
)
def test_connection() -> str:
    """Test connection tool."""
    return "MCP server is working with stdio transport!"


@mcp.tool(
    name="list_users",
    description="Mock list users tool for testing",
)
def list_users(domain: str = "example.com") -> str:
    """Mock list users function."""
    return f"Mock users from domain: {domain}"


if __name__ == "__main__":
    print("Starting simple MCP server with stdio transport...")
    # Use stdio transport - this is the key change
    mcp.run(transport="stdio")
