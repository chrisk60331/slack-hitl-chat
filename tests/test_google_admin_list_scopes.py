from __future__ import annotations

from typing import Any

import pytest

from google_mcp.google_admin.list_scopes import (
    get_current_token_scopes,
    parse_scopes_from_tokeninfo,
)


def test_parse_scopes_from_tokeninfo_splits_and_sorts() -> None:
    tokeninfo: dict[str, str] = {
        "scope": "https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/admin.directory.user"
    }
    scopes = parse_scopes_from_tokeninfo(tokeninfo)
    assert scopes == [
        "https://www.googleapis.com/auth/admin.directory.user",
        "https://www.googleapis.com/auth/drive",
    ]


class _FakeCredentials:
    def __init__(
        self, token: str | None = None, valid: bool = False, expired: bool = True
    ) -> None:
        self.token = token
        self.valid = valid
        self.expired = expired

    def refresh(self, request: Any) -> None:  # noqa: ARG002 - test double signature
        # Simulate obtaining a token
        self.token = "fake-access-token"
        self.valid = True
        self.expired = False


def test_get_current_token_scopes_monkeypatched_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Patch credentials factory
    monkeypatch.setattr(
        "google_mcp.google_admin.list_scopes.get_google_credentials",
        lambda: _FakeCredentials(),
        raising=True,
    )

    # Patch HTTP call
    class _Resp:
        def raise_for_status(self) -> None:  # noqa: D401 - minimal test double
            """No-op success."""

        def json(self) -> dict[str, str]:
            return {
                "scope": "https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/admin.directory.user"
            }

    monkeypatch.setattr(
        "google_mcp.google_admin.list_scopes.requests.get",
        lambda *args, **kwargs: _Resp(),  # noqa: ANN002, ANN003 - test double
        raising=True,
    )

    scopes = get_current_token_scopes()
    assert "https://www.googleapis.com/auth/drive" in scopes
    assert "https://www.googleapis.com/auth/admin.directory.user" in scopes
