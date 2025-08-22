import json
from typing import Dict

import pytest

from totp_mcp.mcp_server import _base32_decode_no_padding, _hotp, _totp_from_base32, _extract_base32_secret


def test_base32_decode_padding():
    # "JBSWY3DPEHPK3PXP" is base32 for "Hello!\xde\xad\xbe\xef" shortened example
    # We just check that no exception and bytes length > 0
    decoded = _base32_decode_no_padding("JBSWY3DPEHPK3PXP")
    assert isinstance(decoded, (bytes, bytearray)) and len(decoded) > 0


def test_hotp_known_vector():
    # RFC 4226 test values (secret "12345678901234567890" base32 is GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ)
    secret = b"12345678901234567890"
    # Counter 1 should yield HOTP 287082 for 6 digits
    assert _hotp(secret, 1, 6) == "287082"


def test_totp_fixed_time():
    # Using base32 for "12345678901234567890"
    base32_secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    # At unix time 59 with 30s period: RFC 6238 TOTP = 287082 for SHA1 and 6 digits (counter=1)
    assert _totp_from_base32(base32_secret, period=30, digits=6, now=59) == "287082"


def test_extract_base32_secret_from_json():
    payload: Dict[str, str] = {"secret": "JBSWY3DPEHPK3PXP"}
    raw = json.dumps(payload)
    assert _extract_base32_secret(raw, "secret") == "JBSWY3DPEHPK3PXP"




