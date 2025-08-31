"""DynamoDB-backed configuration store for MCP servers and policy rules.

Provides typed CRUD helpers for:
- MCP servers: list of alias/path/enabled
- Policy rules: list of `PolicyRule` from `src.policy`

Environment:
- CONFIG_TABLE_NAME: DynamoDB table with hash key `config_key`

Workspace rules:
- Type hints and docstrings
- Pydantic v2 models for validation
"""

from __future__ import annotations

from typing import Any, Iterable

import os
from pydantic import BaseModel, Field

from .dynamodb_utils import get_table
from .policy import PolicyRule


CONFIG_KEY_MCP_SERVERS = "mcp_servers"
CONFIG_KEY_POLICIES = "policies"


def _get_config_table_name() -> str:
    """Return the DynamoDB config table name from environment.

    Raises:
        ValueError: if CONFIG_TABLE_NAME is unset.
    """

    name = os.environ.get("CONFIG_TABLE_NAME", "").strip()
    if not name:
        raise ValueError("CONFIG_TABLE_NAME environment variable is required")
    return name


def _get_config_table() -> Any:
    """Return the DynamoDB Table resource for the config table."""
    # raise ValueError(f"Getting config table {_get_config_table_name()} local_dev {os.getenv('LOCAL_DEV', 'false')}")
    return get_table(_get_config_table_name())


class MCPServer(BaseModel):
    """MCP server configuration entry."""

    alias: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)
    enabled: bool = True


class MCPServersConfig(BaseModel):
    """Container model for all MCP servers."""

    servers: list[MCPServer] = Field(default_factory=list)


class PoliciesConfig(BaseModel):
    """Container model for policy rules."""

    rules: list[PolicyRule] = Field(default_factory=list)


def get_mcp_servers() -> MCPServersConfig:
    """Fetch MCP servers configuration from DynamoDB.

    Returns:
        MCPServersConfig: Parsed configuration. Empty if not found.
    """

    table = _get_config_table()
    resp = table.get_item(Key={"config_key": CONFIG_KEY_MCP_SERVERS})
    item = resp.get("Item") or {}
    servers = item.get("servers", [])
    return MCPServersConfig(servers=[MCPServer(**s) for s in servers])


def put_mcp_servers(servers: Iterable[MCPServer]) -> None:
    """Replace MCP servers configuration in DynamoDB.

    Args:
        servers: Iterable of MCPServer entries to persist.
    """

    table = _get_config_table()
    payload = {
        "config_key": CONFIG_KEY_MCP_SERVERS,
        "servers": [s.model_dump() for s in servers],
    }
    table.put_item(Item=payload)


def get_policies() -> PoliciesConfig:
    """Fetch policy rules from DynamoDB.

    Returns:
        PoliciesConfig: Parsed policy configuration; empty if not found.
    """

    table = _get_config_table()
    resp = table.get_item(Key={"config_key": CONFIG_KEY_POLICIES})
    item = resp.get("Item") or {}
    rules = item.get("rules", [])
    return PoliciesConfig(rules=[PolicyRule(**r) for r in rules])


def put_policies(rules: Iterable[PolicyRule]) -> None:
    """Replace policy rules in DynamoDB.

    Args:
        rules: Iterable of PolicyRule entries to persist.
    """

    table = _get_config_table()
    payload = {
        "config_key": CONFIG_KEY_POLICIES,
        "rules": [r.model_dump() for r in rules],
    }
    table.put_item(Item=payload)


