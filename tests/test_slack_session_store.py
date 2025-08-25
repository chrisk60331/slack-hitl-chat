import os
from unittest.mock import MagicMock, patch

import pytest

from src.slack_session_store import SlackSessionStore


@patch("boto3.resource")
def test_put_and_get_session_id(mock_resource: MagicMock) -> None:
    os.environ["SLACK_SESSIONS_TABLE"] = "test-slack-sessions"
    table = MagicMock()
    mock_resource.return_value.Table.return_value = table

    # Simulate get_item result after put
    table.get_item.return_value = {
        "Item": {"thread_key": "C:1.1", "session_id": "s-123"}
    }

    store = SlackSessionStore()
    store.put_session_id("C", "1.1", "s-123", ttl_seconds=10)
    assert table.put_item.called

    value = store.get_session_id("C", "1.1")
    assert value == "s-123"


def test_requires_env() -> None:
    os.environ.pop("SLACK_SESSIONS_TABLE", None)
    with pytest.raises(ValueError):
        SlackSessionStore()
