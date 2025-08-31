"""Centralized DynamoDB helpers for AgentCore.

Provides a single place to construct boto3 DynamoDB resources and tables.

Workspace rules:
- Type hints and docstrings
- Prefer top-level imports (no lazy imports)
"""

from __future__ import annotations

import os
from typing import Any

import boto3


def get_dynamodb_resource() -> Any:
    """Return a configured boto3 DynamoDB resource.

    Honors LOCAL_DEV setup to support local DynamoDB containers.
    """
    # if os.getenv("LOCAL_DEV", "false").lower() == "true":
    #     params: dict[str, Any] = {
    #         "endpoint_url": os.environ.get(
    #             "DYNAMODB_LOCAL_ENDPOINT",
    #             "http://localhost:8000",
    #         ),
    #         "aws_access_key_id": os.environ.get("AWS_ACCESS_KEY_ID", "test"),
    #         "aws_secret_access_key": os.environ.get(
    #             "AWS_SECRET_ACCESS_KEY", "test"
    #         ),
    #     }
    # else:
    params = {}
    return boto3.resource(
        "dynamodb",
        region_name="us-west-2",
        **params,
    )


def get_table(table_name: str) -> Any:
    """Return a DynamoDB table handle by name.

    Args:
        table_name: Name of the DynamoDB table

    Returns:
        boto3 DynamoDB Table resource
    """
    resource = get_dynamodb_resource()
    return resource.Table(table_name)


def get_approval_table() -> Any:
    """Return the approvals table configured by `TABLE_NAME` env var."""
    name = os.environ.get("TABLE_NAME", "")
    if not name:
        raise ValueError("TABLE_NAME environment variable is required")
    return get_table(name)
