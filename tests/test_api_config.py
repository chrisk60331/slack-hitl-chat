from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api import app


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("LOCAL_DEV", "true")
    monkeypatch.setenv("DYNAMODB_LOCAL_ENDPOINT", "http://localhost:8000")
    monkeypatch.setenv("CONFIG_TABLE_NAME", "agentcore-test-config")


@pytest.fixture(autouse=True)
def _ensure_table() -> None:
    import boto3

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


def test_config_servers_roundtrip() -> None:
    client = TestClient(app)
    payload = {
        "servers": [
            {"alias": "google", "path": "/srv/google.py", "enabled": True},
            {"alias": "jira", "path": "/srv/jira.py", "enabled": False},
        ]
    }
    r = client.put("/config/mcp-servers", json=payload)
    assert r.status_code == 200
    r = client.get("/config/mcp-servers")
    assert r.status_code == 200
    data = r.json()
    assert len(data["servers"]) == 2


def test_config_policies_roundtrip() -> None:
    client = TestClient(app)
    payload = {
        "rules": [
            {
                "name": "require_doc_access",
                "categories": ["non_sow_document_access"],
                "require_approval": True,
            }
        ]
    }
    r = client.put("/config/policies", json=payload)
    assert r.status_code == 200
    r = client.get("/config/policies")
    assert r.status_code == 200
    assert r.json()["rules"][0]["name"] == "require_doc_access"
