"""Slack session mapping store backed by DynamoDB.

Maps Slack `channel_id:thread_ts` to AgentCore `session_id` for context
persistence. Uses a composite primary key with TTL for automatic cleanup.

Conforms to workspace rules:
- Type hints and docstrings
- Prefer deque/generators where helpful (not needed here)
- Pydantic not required for this simple store
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import boto3


@dataclass(slots=True)
class SlackSessionStore:
    """DynamoDB-backed mapping from Slack thread to AgentCore session id.

    Table schema (proposed):
      - PK: `thread_key` (S) formatted as "{channel_id}:{thread_ts}"
      - Attributes: `session_id` (S), `updated_at` (N), optional `ttl` (N)
    """

    # Read environment at instantiation time (tests set env within test functions)
    table_name: str = field(
        default_factory=lambda: os.environ.get("SLACK_SESSIONS_TABLE", "")
    )
    region_name: str = field(
        default_factory=lambda: os.environ.get("AWS_REGION", "us-east-1")
    )
    _table: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.table_name:
            raise ValueError(
                "SLACK_SESSIONS_TABLE environment variable is required"
            )
        resource = boto3.resource("dynamodb", region_name=self.region_name)
        self._table = resource.Table(self.table_name)

    @staticmethod
    def _thread_key(channel_id: str, thread_ts: str) -> str:
        return f"{channel_id}:{thread_ts}"

    def get_session_id(self, channel_id: str, thread_ts: str) -> str | None:
        """Return stored session id for a Slack thread, if present.

        Args:
            channel_id: Slack channel id
            thread_ts: Slack thread timestamp

        Returns:
            Session id string or None if no mapping exists.
        """
        key = {"thread_key": self._thread_key(channel_id, thread_ts)}
        resp = self._table.get_item(Key=key)
        item = resp.get("Item")
        return None if not item else str(item.get("session_id") or "") or None

    def put_session_id(
        self,
        channel_id: str,
        thread_ts: str,
        session_id: str,
        ttl_seconds: int = 60 * 60 * 24 * 14,
    ) -> None:
        """Create/update session mapping with TTL (default 14 days).

        Args:
            channel_id: Slack channel id
            thread_ts: Slack thread timestamp
            session_id: AgentCore session id to associate
            ttl_seconds: Time to live from now in seconds
        """
        now = int(time.time())
        item = {
            "thread_key": self._thread_key(channel_id, thread_ts),
            "session_id": session_id,
            "updated_at": now,
            "ttl": now + int(ttl_seconds),
        }
        self._table.put_item(Item=item)
