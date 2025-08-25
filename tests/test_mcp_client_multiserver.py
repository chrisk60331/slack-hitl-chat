
import pytest

from src.mcp_client import MCPClient


@pytest.mark.asyncio
async def test_connect_to_servers_registry(monkeypatch):
    client = MCPClient()

    class FakeTool:
        def __init__(self, name: str):
            self.name = name
            self.description = "desc"
            self.inputSchema = {"type": "object"}

    class FakeResp:
        def __init__(self, tools):
            self.tools = tools

    class FakeSession:
        async def initialize(self):
            return None

        async def list_tools(self):
            return FakeResp([FakeTool("t1"), FakeTool("t2")])

    class FakeStdioClient:
        async def __aenter__(self):
            return (object(), object())

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeClientSession:
        def __init__(self, _stdio, _write):
            self._inner = FakeSession()

        async def __aenter__(self):
            return self._inner

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "src.mcp_client.stdio_client", lambda _params: FakeStdioClient()
    )
    monkeypatch.setattr("src.mcp_client.ClientSession", FakeClientSession)

    await client.connect_to_servers({"a": "s1.py", "b": "s2.py"})
    assert set(client.sessions.keys()) == {"a", "b"}
    # Tools should be qualified
    tools = []
    for alias, session in client.sessions.items():
        resp = await session.list_tools()
        tools.extend([f"{alias}/{t.name}" for t in resp.tools])
    assert set(tools) == {"a/t1", "a/t2", "b/t1", "b/t2"}
