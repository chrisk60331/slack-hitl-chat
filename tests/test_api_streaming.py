import pytest
from httpx import ASGITransport, AsyncClient

from src.api import app


@pytest.mark.asyncio
async def test_create_session_and_post_and_stream() -> None:
    # httpx >=0.25 uses ASGITransport for in-process testing
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # create session
        r = await ac.post("/gateway/v1/sessions")
        assert r.status_code == 200
        session_id = r.json()["session_id"]

        # post message
        r = await ac.post(
            f"/gateway/v1/sessions/{session_id}/messages",
            json={"query": "hello", "user_id": "u"},
        )
        assert r.status_code == 200
        message_id = r.json()["message_id"]

        # start stream (consume a few events)
        r = await ac.get(
            f"/gateway/v1/sessions/{session_id}/stream?cursor={message_id}",
            timeout=None,
        )
        assert r.status_code == 200
        # SSE payload comes as a byte stream. For unit test, ensure we can iterate some bytes.
        # httpx returns an async stream; read small chunk to verify it's producing.
        content = b""
        async for chunk in r.aiter_bytes():
            content += chunk
            if len(content) > 0:
                break
        assert len(content) > 0
