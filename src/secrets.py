"""Secrets Manager helper utilities.

Provides cached helpers to read application secrets from AWS Secrets Manager.

Rules followed:
- Type hints and docstrings for all functions
- Pydantic v2-style types are used where appropriate
- Caches lookups for performance using lru_cache
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict, Optional

import boto3


@lru_cache(maxsize=128)
def _get_secrets_client() -> Any:
    """Return a cached boto3 Secrets Manager client.

    Returns:
        Boto3 Secrets Manager client bound to AWS_REGION.
    """
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.client("secretsmanager", region_name=region)


@lru_cache(maxsize=256)
def get_secret_string(secret_name: str) -> str:
    """Fetch a secret string value by name with caching.

    Args:
        secret_name: Full name of the secret in Secrets Manager.

    Returns:
        Secret value as a raw string. If the secret is JSON-formatted, consider
        using `get_secret_json`.
    """
    client = _get_secrets_client()
    response = client.get_secret_value(SecretId=secret_name)
    if "SecretString" in response:
        return str(response["SecretString"])  # type: ignore[return-value]
    # Fallback if binary secret
    return response.get("SecretBinary", b"").decode("utf-8")


@lru_cache(maxsize=256)
def get_secret_json(secret_name: str) -> Dict[str, Any]:
    """Fetch and parse a JSON secret by name.

    Args:
        secret_name: Full name of the secret in Secrets Manager.

    Returns:
        Parsed JSON object.
    """
    raw = get_secret_string(secret_name)
    try:
        return json.loads(raw)
    except Exception:
        return {"value": raw}


def put_secret_string(secret_name: str, value: str) -> None:
    """Create or update a plain string secret.

    Args:
        secret_name: Secret name (path-like names are recommended).
        value: Secret string to store.
    """
    client = _get_secrets_client()
    try:
        client.describe_secret(SecretId=secret_name)
        client.put_secret_value(SecretId=secret_name, SecretString=value)
    except client.exceptions.ResourceNotFoundException:
        client.create_secret(Name=secret_name, SecretString=value)


def put_secret_json(secret_name: str, payload: Dict[str, Any]) -> None:
    """Create or update a JSON secret.

    Args:
        secret_name: Secret name.
        payload: JSON-serializable dict to store.
    """
    put_secret_string(secret_name, json.dumps(payload))


