from __future__ import annotations

import os

import pytest

from src.mcp_client import MCPClient


@pytest.fixture(autouse=True)
def _aws_region_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure MCPClient __init__ does not KeyError
    monkeypatch.setenv("AWS_REGION", os.getenv("AWS_REGION", "us-east-1"))


def test_set_disabled_tools_map_normalizes_and_checks() -> None:
    client = MCPClient()

    # Mix of short and qualified names should normalize to short names
    client.set_disabled_tools_map(
        {
            "google": ["files_list", "google__files_delete"],
            "jira": {"jira__issue_delete", "issue_update"},
        }
    )

    assert client.is_tool_allowed("google", "files_list") is False
    assert client.is_tool_allowed("google", "files_delete") is False
    assert client.is_tool_allowed("google", "files_get") is True

    assert client.is_tool_allowed("jira", "issue_delete") is False
    assert client.is_tool_allowed("jira", "issue_update") is False
    assert client.is_tool_allowed("jira", "issue_create") is True


def test_is_tool_allowed_defaults_to_allowed_when_alias_missing() -> None:
    client = MCPClient()
    # No mapping set yet
    assert client.is_tool_allowed("unknown", "anything") is True


