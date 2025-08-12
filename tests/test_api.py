from __future__ import annotations

import pytest
import httpx
import time
from httpx import AsyncClient

from src.api import app


def _sign_slack_request(signing_secret: str, body: bytes, timestamp: str) -> str:
    import hmac, hashlib
    basestring = f"v0:{timestamp}:{body.decode('utf-8')}".encode('utf-8')
    digest = hmac.new(signing_secret.encode('utf-8'), basestring, hashlib.sha256).hexdigest()
    return f"v0={digest}"


@pytest.mark.asyncio
async def test_healthz() -> None:
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "ok"


@pytest.mark.asyncio
async def test_slack_interactions_signature_invalid() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/slack/interactions",
            content=b"payload=%7B%22type%22%3A%22block_actions%22%7D",
            headers={
                "X-Slack-Request-Timestamp": "1",
                "X-Slack-Signature": "v0=invalid",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_slack_interactions_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    # Prepare payload
    payload = {
        "type": "block_actions",
        "user": {"id": "U123"},
        "actions": [
            {
                "action_id": "approve",
                "value": "{\"request_id\":\"req-123\",\"action\":\"approve\"}",
            }
        ],
        "response_url": "https://example.com/response",
    }
    import json as _json
    form_body = f"payload={_json.dumps(payload)}".encode("utf-8")
    ts = str(int(time.time()))
    secret = "testsecret"
    sig = _sign_slack_request(secret, form_body, ts)

    # Stub approval decision handler and response_url call
    class DummyResp:
        status_code = 200

    called = {"dec": False, "resp": False}

    def fake_handle(event):
        called["dec"] = True
        return {"statusCode": 200, "body": {}}

    def fake_post(url, json=None, timeout=5):
        called["resp"] = True
        return DummyResp()

    monkeypatch.setenv("SLACK_SIGNING_SECRET", secret)
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    from src import approval_handler as ah
    from src import slack_helper as sh
    monkeypatch.setattr(ah, "_handle_approval_decision", fake_handle)
    monkeypatch.setattr(sh.requests, "post", fake_post)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/slack/interactions",
            content=form_body,
            headers={
                "X-Slack-Request-Timestamp": ts,
                "X-Slack-Signature": sig,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        assert resp.status_code == 200
        assert resp.json().get("status") == "ok"
        assert called["dec"] is True
        assert called["resp"] is True


