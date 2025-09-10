"""Analytics utilities for aggregating approval requests.

Provides pure functions to compute counts by requester and by status from
iterables of DynamoDB items. These are used by the Flask Admin UI analytics
page, but remain framework-agnostic for easier testing.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable


def aggregate_requests_by_user(items: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Return counts of requests grouped by requester.

    Args:
        items: Iterable of request records (e.g., DynamoDB items). Each item may
            contain a ``requester`` key. Missing or empty values are grouped
            under "unknown".

    Returns:
        Mapping from requester identifier to number of requests.
    """

    counter: Counter[str] = Counter()
    for item in items:
        requester = str(item.get("requester") or "").strip() or "unknown"
        counter[requester] += 1
    # Sort descending by count then by requester for stable display
    return dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))


def aggregate_requests_by_status(items: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Return counts of requests grouped by approval status.

    Args:
        items: Iterable of request records. Each item may contain an
            ``approval_status`` field. Missing or empty values are grouped under
            "unknown".

    Returns:
        Mapping from status to number of requests.
    """

    counter: Counter[str] = Counter()
    for item in items:
        status = str(item.get("approval_status") or item.get("status") or "").strip() or "unknown"
        counter[status] += 1
    def _sort_key(entry: tuple[str, int]) -> tuple[int, int, str]:
        status, count = entry
        # Prioritize higher counts; on tie, show "unknown" first, then alpha
        unknown_priority = 0 if status == "unknown" else 1
        return (-count, unknown_priority, status)

    return dict(sorted(counter.items(), key=_sort_key))


