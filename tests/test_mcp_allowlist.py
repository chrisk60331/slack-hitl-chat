from __future__ import annotations

import os
from typing import Any

import pytest

from src.mcp_client import MCPClient


class DummySession:
    class Tool:
        def __init__(self, name: str) -> None:
            self.name = name

    class ToolsResp:
        def __init__(self, tools: list[Any]) -> None:
            self.tools = tools

    async def list_tools(self) -> Any:
        return self.ToolsResp([self.Tool("foo"), self.Tool("bar")])

    async def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        class Result:
            def __init__(self) -> None:
                self.content = "ok"

        return Result()


@pytest.mark.asyncio
async def test_mcp_client_enforces_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("MCP_ALLOWED_TOOLS", "alias__foo")
    client = MCPClient()
    client.sessions = {"alias": DummySession()}

    # Only alias__foo should be exposed; bar filtered out
    tools = []
    tools_resp = await client.sessions["alias"].list_tools()
    for t in tools_resp.tools:
        if client.is_tool_allowed("alias", t.name):
            tools.append(f"alias__{t.name}")
    assert tools == ["alias__foo"]





