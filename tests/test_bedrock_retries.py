import json
from typing import Any

import pytest

from src.mcp_client import MCPClient


class TransientError(Exception):
    pass


def test_invoke_with_retries_transient_then_success(monkeypatch):
    client = MCPClient()

    calls: dict[str, int] = {"n": 0}

    class FakeClientError(TransientError):
        # Simulate botocore ClientError-like with response code
        def __init__(self, code: str):
            super().__init__(code)
            self.response = {"Error": {"Code": code}}

    def fake_is_retryable(exc: Exception) -> bool:
        return isinstance(exc, FakeClientError)

    def fake_invoke_model(*_args: Any, **_kwargs: Any):
        calls["n"] += 1
        if calls["n"] < 3:
            raise FakeClientError("ServiceUnavailableException")
        return {
            "body": type(
                "B", (), {"read": lambda self: json.dumps({"content": []}).encode()}
            )()
        }

    monkeypatch.setattr(client, "_is_retryable_bedrock_error", fake_is_retryable)
    monkeypatch.setattr(client.bedrock, "invoke_model", fake_invoke_model)

    resp = client._invoke_with_retries(
        model_id="m", body={"k": 1}, max_retries=5, base_delay_seconds=0.0
    )
    assert "body" in resp
    assert calls["n"] == 3


def test_invoke_stream_with_retries_gives_up(monkeypatch):
    client = MCPClient()

    class FakeClientError(TransientError):
        def __init__(self, code: str):
            super().__init__(code)
            self.response = {"Error": {"Code": code}}

    def fake_is_retryable(exc: Exception) -> bool:
        return isinstance(exc, FakeClientError)

    def fake_invoke_stream(*_args: Any, **_kwargs: Any):
        raise FakeClientError("ServiceUnavailableException")

    monkeypatch.setattr(client, "_is_retryable_bedrock_error", fake_is_retryable)
    monkeypatch.setattr(
        client.bedrock, "invoke_model_with_response_stream", fake_invoke_stream
    )

    with pytest.raises(FakeClientError):
        client._invoke_stream_with_retries(
            model_id="m", body={}, max_retries=2, base_delay_seconds=0.0
        )
