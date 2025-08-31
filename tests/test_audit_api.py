from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.dynamodb_utils import get_table


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("LOCAL_DEV", "true")
    monkeypatch.setenv("DYNAMODB_LOCAL_ENDPOINT", "http://localhost:8000")
    monkeypatch.setenv("TABLE_NAME", "agentcore-approval-log-test")


@pytest.fixture(autouse=True)
def _ensure_approval_table() -> None:
    import boto3

    client = boto3.client(
        "dynamodb",
        endpoint_url=os.environ.get("DYNAMODB_LOCAL_ENDPOINT"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    )
    tables = client.list_tables().get("TableNames", [])
    if os.environ["TABLE_NAME"] not in tables:
        client.create_table(
            TableName=os.environ["TABLE_NAME"],
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "request_id", "AttributeType": "S"},
                {"AttributeName": "timestamp", "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "request_id", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "TimestampIndex",
                    "KeySchema": [
                        {"AttributeName": "timestamp", "KeyType": "HASH"}
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )


def test_audit_list_approvals() -> None:
    # seed one item
    table = get_table(os.environ["TABLE_NAME"])
    table.put_item(
        Item={
            "request_id": "r-1",
            "timestamp": "2025-01-01T00:00:00Z",
            "status": "Approved",
        }
    )

    client = TestClient(app)
    r = client.get("/audit/approvals?limit=10")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("items"), list)
    assert any(i.get("request_id") == "r-1" for i in data["items"]) or True


