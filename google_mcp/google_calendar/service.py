from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/calendar",  # full calendar scope
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _iso_has_tz(value: str) -> bool:
    try:
        # Accept Z or offset
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.tzinfo is not None
    except Exception:
        return False


class GoogleCalendarClient:
    """Thin wrapper over Google Calendar API for MCP tools.

    Handles OAuth2 installed-app flow using env client credentials.
    Tokens are cached to GCAL_TOKEN_PATH or user cache dir.
    """

    def __init__(self, credentials: Credentials | None = None) -> None:
        self._service = None
        self._credentials = credentials

    def _ensure_service(self):
        if self._service is not None:
            return self._service

        if self._credentials is None or not self._credentials.valid:
            token_path = os.getenv(
                "GCAL_TOKEN_PATH",
                os.path.expanduser("~/.config/agentcore/gcal_token.json"),
            )
            creds: Credentials | None = None
            if os.path.exists(token_path):
                try:
                    creds = Credentials.from_authorized_user_file(
                        token_path, SCOPES
                    )
                except Exception:
                    creds = None
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    # Build client config from env vars
                    client_id = _require_env("GCAL_CLIENT_ID")
                    client_secret = _require_env("GCAL_CLIENT_SECRET")
                    redirect_uri = _require_env("GCAL_REDIRECT_URI")
                    flow = InstalledAppFlow.from_client_config(
                        {
                            "installed": {
                                "client_id": client_id,
                                "client_secret": client_secret,
                                "redirect_uris": [redirect_uri],
                                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                                "token_uri": "https://oauth2.googleapis.com/token",
                            }
                        },
                        SCOPES,
                    )
                    creds = flow.run_local_server(port=0)
                os.makedirs(os.path.dirname(token_path), exist_ok=True)
                with open(token_path, "w") as f:
                    f.write(creds.to_json())
            self._credentials = creds

        self._service = build(
            "calendar",
            "v3",
            credentials=self._credentials,
            cache_discovery=False,
        )
        return self._service

    # --------------- API methods ---------------
    def list_calendars(self) -> dict[str, Any]:
        svc = self._ensure_service()
        resp = svc.calendarList().list().execute()
        return resp

    def freebusy(
        self,
        calendar_ids: list[str],
        time_min: str,
        time_max: str,
        timezone: str | None,
    ) -> dict[str, Any]:
        svc = self._ensure_service()
        if not _iso_has_tz(time_min) or not _iso_has_tz(time_max):
            raise ValueError(
                "time_min and time_max must be ISO8601 with timezone"
            )
        body: dict[str, Any] = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": cid} for cid in calendar_ids],
        }
        if timezone:
            body["timeZone"] = timezone
        return svc.freebusy().query(body=body).execute()

    def create_event(
        self, body: dict[str, Any], calendar_id: str
    ) -> dict[str, Any]:
        svc = self._ensure_service()
        return svc.events().insert(calendarId=calendar_id, body=body).execute()

    def get_event(self, calendar_id: str, event_id: str) -> dict[str, Any]:
        svc = self._ensure_service()
        return (
            svc.events()
            .get(calendarId=calendar_id, eventId=event_id)
            .execute()
        )

    def delete_event(self, calendar_id: str, event_id: str) -> dict[str, Any]:
        svc = self._ensure_service()
        svc.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        return {
            "status": "deleted",
            "calendar_id": calendar_id,
            "event_id": event_id,
        }
