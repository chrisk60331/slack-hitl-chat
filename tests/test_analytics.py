from __future__ import annotations

from src.analytics import aggregate_requests_by_status, aggregate_requests_by_user


def test_aggregate_requests_by_user_handles_missing_and_sorts() -> None:
    items = [
        {"requester": "alice@example.com"},
        {"requester": "bob@example.com"},
        {"requester": "alice@example.com"},
        {},
        {"requester": "  "},
    ]
    result = aggregate_requests_by_user(items)
    # alice:2, bob:1, unknown:2
    assert list(result.items()) == [
        ("alice@example.com", 2),
        ("unknown", 2),
        ("bob@example.com", 1),
    ]


def test_aggregate_requests_by_status_accepts_both_fields() -> None:
    items = [
        {"approval_status": "Approved"},
        {"approval_status": "Approval Required"},
        {"status": "Approved"},
        {"status": ""},
    ]
    result = aggregate_requests_by_status(items)
    # Approved:2, unknown:1, Approval Required:1
    assert list(result.items()) == [
        ("Approved", 2),
        ("unknown", 1),
        ("Approval Required", 1),
    ]



