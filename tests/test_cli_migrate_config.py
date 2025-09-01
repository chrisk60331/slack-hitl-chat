from __future__ import annotations

import os

from click.testing import CliRunner

from src.cli import cli
from src.config_store import get_mcp_servers, get_policies


def _ensure_local_dynamodb() -> None:
    import boto3

    os.environ.setdefault("AWS_REGION", "us-east-1")
    os.environ.setdefault("LOCAL_DEV", "true")
    os.environ.setdefault("DYNAMODB_LOCAL_ENDPOINT", "http://localhost:8000")
    os.environ.setdefault("CONFIG_TABLE_NAME", "agentcore-test-config")

    client = boto3.client(
        "dynamodb",
        endpoint_url=os.environ.get("DYNAMODB_LOCAL_ENDPOINT"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    )
    tables = client.list_tables().get("TableNames", [])
    if os.environ["CONFIG_TABLE_NAME"] not in tables:
        client.create_table(
            TableName=os.environ["CONFIG_TABLE_NAME"],
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "config_key", "AttributeType": "S"}
            ],
            KeySchema=[{"AttributeName": "config_key", "KeyType": "HASH"}],
        )


def test_cli_migrate_config_servers_and_policies(monkeypatch) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["migrate-config", "--include", "all"])
    assert result.exit_code == 0

    servers = get_mcp_servers().servers
    assert len(servers) >= 3
    assert {s.alias for s in servers} >= {"google", "jira", "calendar"}

    policies = get_policies().rules
    assert len(policies) >= 1
