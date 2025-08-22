import os
import pytest

from google_mcp.google_calendar.service import _iso_has_tz
from google_mcp.google_calendar.models import CreateEventRequest, Attendee
from google_mcp.google_calendar import mcp_server as cal_server


def test_iso_has_tz_valid_with_offset():
    assert _iso_has_tz("2025-01-01T10:00:00-05:00") is True


def test_iso_has_tz_valid_with_z():
    assert _iso_has_tz("2025-01-01T10:00:00Z") is True


def test_iso_has_tz_invalid_no_tz():
    assert _iso_has_tz("2025-01-01T10:00:00") is False


def test_validate_attendees_allowed_domain(monkeypatch):
    monkeypatch.setenv("GCAL_ALLOWED_DOMAINS", "example.com, other.org")
    # Should not raise
    cal_server._validate_attendees([{"email": "user@example.com"}])


def test_validate_attendees_disallowed_domain(monkeypatch):
    monkeypatch.setenv("GCAL_ALLOWED_DOMAINS", "example.com")
    with pytest.raises(ValueError):
        cal_server._validate_attendees([{"email": "user@not-allowed.org"}])


def test_create_event_request_email_validation():
    # Valid email
    req = CreateEventRequest(
        calendar_id="primary",
        summary="Test",
        start="2025-01-01T09:00:00-05:00",
        end="2025-01-01T10:00:00-05:00",
        attendees=[Attendee(email="alice@example.com")],
    )
    assert req.summary == "Test"

    # Invalid email should raise during model creation
    with pytest.raises(Exception):
        CreateEventRequest(
            calendar_id="primary",
            summary="Test",
            start="2025-01-01T09:00:00-05:00",
            end="2025-01-01T10:00:00-05:00",
            attendees=[Attendee(email="not-an-email")],
        )




