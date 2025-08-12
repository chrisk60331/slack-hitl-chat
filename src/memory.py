"""Short-term memory service for AgentCore orchestrator.

This module provides a lightweight, token-aware short-term memory using a
deque. It is designed to be integrated by the orchestrator when constructing
prompts for the MCP client without changing the MCP client implementation.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Iterable, List, Tuple


Message = Tuple[str, str]


@dataclass(slots=True)
class ShortTermMemory:
    """A compact rolling memory of recent conversation turns.

    Stores (role, content) pairs with a fixed maximum number of turns. This is
    intentionally minimal and fast.
    """

    max_turns: int = 6
    _messages: Deque[Message] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._messages = deque(maxlen=self.max_turns)

    def append(self, role: str, content: str) -> None:
        """Append a message.

        Args:
            role: The message role (e.g., "user", "assistant", "system").
            content: The message content.
        """

        self._messages.append((role, content))

    def extend(self, messages: Iterable[Message]) -> None:
        """Append multiple messages."""

        for role, content in messages:
            self.append(role, content)

    def as_prompt_prefix(self) -> str:
        """Return a compact textual prefix capturing recent context."""

        if not self._messages:
            return ""

        lines: List[str] = [
            "Context recap (recent messages):",
        ]
        for role, content in self._messages:
            trimmed = content.strip()
            if len(trimmed) > 500:
                trimmed = trimmed[:500] + "..."
            lines.append(f"- {role}: {trimmed}")

        return "\n".join(lines)


