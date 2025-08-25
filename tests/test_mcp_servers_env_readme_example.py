import os


def test_readme_mcp_servers_example_includes_calendar_and_allows_totp(monkeypatch):
    example = (
        "google=/abs/path/google_mcp/google_admin/mcp_server.py;"
        "jira=/abs/path/jira_mcp/server.py;"
        "calendar=/abs/path/google_mcp/google_calendar/mcp_server.py;"
        "totp=/abs/path/totp_mcp/mcp_server.py"
    )
    monkeypatch.setenv("MCP_SERVERS", example)
    assert "totp=/abs/path/totp_mcp/mcp_server.py" in os.environ["MCP_SERVERS"]
