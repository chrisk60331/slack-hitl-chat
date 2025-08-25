from __future__ import annotations

import os
import sys
from typing import Any

from fastmcp import FastMCP

sys.path.append("/var/task/")
# Add the google_mcp directory to the path for local development
current_dir = os.path.dirname(os.path.abspath(__file__))
google_mcp_dir = os.path.join(current_dir, "..")
sys.path.append(google_mcp_dir)

from google_calendar.models import (
    CreateEventRequest,
    DeleteEventRequest,
    FreeBusyRequest,
    GetEventRequest,
    ListCalendarsRequest,
)
from google_calendar.service import GoogleCalendarClient, _iso_has_tz

mcp = FastMCP(
    "Google Calendar MCP Server",
    dependencies=["google_calendar@./google_calendar"],
)


def _allowed_domains() -> list[str]:
    raw = os.getenv("GCAL_ALLOWED_DOMAINS", "").strip()
    if not raw:
        return []
    return [d.strip().lower() for d in raw.split(",") if d.strip()]


def _validate_attendees(attendees: list[dict[str, Any]]) -> None:
    domains = _allowed_domains()
    if not domains:
        return
    for a in attendees:
        email = (a.get("email") or "").lower()
        if "@" not in email:
            raise ValueError("attendee email invalid")
        domain = email.split("@", 1)[1]
        if domain not in domains:
            raise ValueError(f"attendee domain not allowed: {domain}")


@mcp.tool(
    name="list_calendars",
    description="List calendars accessible to the authenticated user",
)
def list_calendars(_: ListCalendarsRequest) -> dict[str, Any]:
    client = GoogleCalendarClient()
    return client.list_calendars()


@mcp.tool(
    name="freebusy",
    description="Batch free/busy across calendars between time_min and time_max (ISO8601+TZ)",
)
def freebusy(request: FreeBusyRequest) -> dict[str, Any]:
    if not request.calendar_ids:
        raise ValueError("calendar_ids required")
    if not _iso_has_tz(request.time_min) or not _iso_has_tz(request.time_max):
        raise ValueError("time_min and time_max must be ISO8601 with timezone")
    client = GoogleCalendarClient()
    return client.freebusy(
        request.calendar_ids, request.time_min, request.time_max, request.timezone
    )


@mcp.tool(
    name="create_event",
    description="Create a calendar event with ISO8601+TZ times. No auto-Meet.",
)
def create_event(request: CreateEventRequest) -> dict[str, Any]:
    # Validate times
    if not _iso_has_tz(request.start) or not _iso_has_tz(request.end):
        raise ValueError("start and end must be ISO8601 with timezone")

    # Validate attendees against allowed domains
    attendees_payload = [a.model_dump() for a in request.attendees]
    _validate_attendees(attendees_payload)

    event_body: dict[str, Any] = {
        "summary": request.summary,
        "description": request.description or "",
        "start": {"dateTime": request.start},
        "end": {"dateTime": request.end},
    }
    if request.location:
        event_body["location"] = request.location
    if attendees_payload:
        event_body["attendees"] = attendees_payload

    # No auto Google Meet. Only attach conferenceData when explicitly provided for Zoom.
    if request.conference == "zoom" and request.conferenceData:
        # Pass-through conferenceData as provided by the caller
        event_body["conferenceData"] = request.conferenceData

    if request.zoom_url:
        # Ensure the Zoom URL is included; prefer location if not set, else append to description
        if not event_body.get("location"):
            event_body["location"] = request.zoom_url
        else:
            desc = event_body.get("description") or ""
            if request.zoom_url not in desc:
                event_body["description"] = (
                    desc + "\n\nJoin: " + request.zoom_url
                ).strip()

    client = GoogleCalendarClient()
    # Important: if conferenceData is set, must set conferenceDataVersion
    insert_kwargs: dict[str, Any] = {}
    if "conferenceData" in event_body:
        insert_kwargs["body"] = event_body
        return client.create_event(event_body, request.calendar_id)
    return client.create_event(event_body, request.calendar_id)


@mcp.tool(name="get_event", description="Get a calendar event by id")
def get_event(request: GetEventRequest) -> dict[str, Any]:
    client = GoogleCalendarClient()
    return client.get_event(request.calendar_id, request.event_id)


@mcp.tool(name="delete_event", description="Delete a calendar event by id")
def delete_event(request: DeleteEventRequest) -> dict[str, Any]:
    client = GoogleCalendarClient()
    return client.delete_event(request.calendar_id, request.event_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
