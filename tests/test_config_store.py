from __future__ import annotations

import os
from typing import Any

import pytest

from src.config_store import (
    MCPServer,
    get_mcp_servers,
    put_mcp_servers,
    get_policies,
    put_policies,
)
from src.policy import PolicyRule, ApprovalCategory
from src.dynamodb_utils import get_table


@pytest.fixture(autouse=True)
def _setup_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("LOCAL_DEV", "true")
    monkeypatch.setenv("DYNAMODB_LOCAL_ENDPOINT", "http://localhost:8000")
    monkeypatch.setenv("CONFIG_TABLE_NAME", "agentcore-test-config")


@pytest.fixture(autouse=True)
def _ensure_table() -> None:
    table = get_table(os.environ["CONFIG_TABLE_NAME"])  # may not exist in CI
    try:
        table.load()
    except Exception:
        # Create if missing (local dynamodb only)
        import boto3

        dynamodb = boto3.client(
            "dynamodb",
            endpoint_url=os.environ.get("DYNAMODB_LOCAL_ENDPOINT"),
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
        )
        dynamodb.create_table(
            TableName=os.environ["CONFIG_TABLE_NAME"],
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "config_key", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "config_key", "KeyType": "HASH"}],
        )


def test_put_and_get_mcp_servers() -> None:
    servers = [
        MCPServer(alias="google", path="/srv/google.py", enabled=True),
        MCPServer(alias="jira", path="/srv/jira.py", enabled=False),
    ]
    put_mcp_servers(servers)
    cfg = get_mcp_servers()
    assert len(cfg.servers) == 2
    assert {s.alias for s in cfg.servers} == {"google", "jira"}


def test_put_and_get_policies() -> None:
    rules = [
        PolicyRule(
            name="require_aws_role",
            categories=[ApprovalCategory.AWS_ROLE_ACCESS],
            require_approval=True,
        )
    ]
    put_policies(rules)
    cfg = get_policies()
    assert len(cfg.rules) == 1
    assert cfg.rules[0].name == "require_aws_role"


