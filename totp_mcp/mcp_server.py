from __future__ import annotations

import base64
import hmac
import os
import struct
import time
from hashlib import sha1
from typing import Any, Dict, Optional

import boto3
from fastmcp import FastMCP
from pydantic import BaseModel, Field


mcp = FastMCP(
    "TOTP MCP Server",
    dependencies=["totp_mcp@./totp_mcp"],
)


class GetTotpCodeRequest(BaseModel):
    """Request to fetch a TOTP code.

    Attributes:
        secret_name: Name of the AWS Secrets Manager secret that contains the
            TOTP secret. The secret value may be a raw base32 secret (string),
            or a JSON object with a key named "secret" holding the base32
            secret.
        key_field: Optional field name to use for extracting the base32 secret
            when the secret is a JSON object. Defaults to "secret".
        period: The time step in seconds. Defaults to 30 seconds.
        digits: Number of digits in the TOTP code. Defaults to 6.
        secret_region: Optional AWS region for the secret. If not provided,
            falls back to AWS_REGION env var or Secrets Manager default chain.
    """

    secret_name: str = Field(..., min_length=1)
    key_field: str = Field(default="secret")
    period: int = Field(default=30, ge=15, le=120)
    digits: int = Field(default=6, ge=6, le=10)
    secret_region: Optional[str] = Field(default=None)


def _base32_decode_no_padding(data: str) -> bytes:
    """Decode a possibly unpadded base32 string into bytes.

    Adds missing padding and ignores spaces; case-insensitive.
    """
    value = data.strip().replace(" ", "").upper()
    # Add required padding for base32 if missing
    missing = (-len(value)) % 8
    if missing:
        value += "=" * missing
    return base64.b32decode(value, casefold=True)


def _hotp(secret: bytes, counter: int, digits: int) -> str:
    """Generate an HOTP code using SHA1.

    Args:
        secret: Raw shared secret bytes.
        counter: Moving factor (8-byte integer).
        digits: Number of digits in the output code.
    """
    counter_bytes = struct.pack("!Q", counter)
    hmac_digest = hmac.new(secret, counter_bytes, sha1).digest()
    offset = hmac_digest[-1] & 0x0F
    code = (
        ((hmac_digest[offset] & 0x7F) << 24)
        | ((hmac_digest[offset + 1] & 0xFF) << 16)
        | ((hmac_digest[offset + 2] & 0xFF) << 8)
        | (hmac_digest[offset + 3] & 0xFF)
    )
    hotp_value = code % (10 ** digits)
    return str(hotp_value).zfill(digits)


def _totp_from_base32(base32_secret: str, period: int, digits: int, now: Optional[int] = None) -> str:
    """Generate a TOTP code from a base32 secret.

    Args:
        base32_secret: Base32-encoded shared secret.
        period: Time step in seconds (default 30).
        digits: Number of digits (default 6).
        now: Optional unix timestamp override for testing.
    """
    unix_time = int(now if now is not None else time.time())
    counter = unix_time // period
    secret_bytes = _base32_decode_no_padding(base32_secret)
    return _hotp(secret_bytes, counter, digits)


def _get_secret_value(secret_name: str, region: Optional[str]) -> str:
    """Fetch a secret string from AWS Secrets Manager.

    Returns SecretString when present, otherwise returns base64 of SecretBinary.
    """
    client_kwargs: Dict[str, Any] = {}
    if region:
        client_kwargs["region_name"] = region
    elif os.environ.get("AWS_REGION"):
        client_kwargs["region_name"] = os.environ.get("AWS_REGION")
    sm = boto3.client("secretsmanager", **client_kwargs)
    resp = sm.get_secret_value(SecretId=secret_name)
    if "SecretString" in resp and resp["SecretString"]:
        return resp["SecretString"]
    return base64.b64encode(resp.get("SecretBinary", b""))


def _extract_base32_secret(secret_value: str, key_field: str) -> str:
    """Extract base32 secret from a raw string or JSON object string."""
    # Try JSON first; fall back to raw string
    try:
        import json

        obj = json.loads(secret_value)
        if isinstance(obj, dict) and key_field in obj:
            return str(obj[key_field])
    except Exception:
        pass
    return secret_value.strip()


@mcp.tool(
    name="get_totp_code",
    description="Fetch a TOTP base32 secret from AWS Secrets Manager and return the current code.",
)
def get_totp_code(request: GetTotpCodeRequest) -> Dict[str, str]:
    """Return the current TOTP code for the secret in Secrets Manager."""
    secret_value = _get_secret_value(request.secret_name, request.secret_region)
    base32_secret = _extract_base32_secret(secret_value, request.key_field)
    code = _totp_from_base32(base32_secret, request.period, request.digits)
    return {"code": code}


@mcp.tool(
    name="generate_totp_code",
    description="Generate the current code.",
)
def generate_totp_code(secret_value) -> Dict[str, str]:
    """Return the current TOTP code for secret_value."""
    base32_secret = _extract_base32_secret(secret_value, secret_value)
    code = _totp_from_base32(base32_secret, 30, 6)
    return {"code": code}


if __name__ == "__main__":
    mcp.run(transport="stdio")


