from __future__ import annotations

from typing import Any

from pydantic import BaseModel, EmailStr, Field


class ListCalendarsRequest(BaseModel):
    """Empty request model for listing calendars."""

    pass


class FreeBusyRequest(BaseModel):
    """Request for free/busy query across multiple calendars."""

    calendar_ids: list[str] = Field(..., description="Calendar IDs to query")
    time_min: str = Field(
        ..., description="ISO8601 start with timezone, e.g. 2025-07-20T09:00:00-04:00"
    )
    time_max: str = Field(
        ..., description="ISO8601 end with timezone, e.g. 2025-07-20T18:00:00-04:00"
    )
    timezone: str | None = Field(
        None, description="IANA TZ database name, e.g. America/New_York"
    )


class Attendee(BaseModel):
    email: EmailStr
    optional: bool = False


class CreateEventRequest(BaseModel):
    """Create a calendar event."""

    calendar_id: str = Field(..., description="Target calendar ID")
    summary: str = Field(..., description="Event title")
    description: str | None = None
    location: str | None = None
    start: str = Field(..., description="ISO8601 start with timezone")
    end: str = Field(..., description="ISO8601 end with timezone")
    attendees: list[Attendee] = Field(default_factory=list)
    conference: str | None = Field(
        None, description="Set to 'zoom' to attach provided conferenceData"
    )
    conferenceData: dict[str, Any] | None = Field(
        default=None,
        description="Pass-through conferenceData only when conference='zoom'",
    )
    zoom_url: str | None = Field(
        default=None,
        description="Zoom URL to include in the event description/location",
    )


class GetEventRequest(BaseModel):
    calendar_id: str
    event_id: str


class DeleteEventRequest(BaseModel):
    calendar_id: str
    event_id: str
