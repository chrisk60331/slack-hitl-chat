import os
from types import SimpleNamespace

import pytest

from jira_mcp.server import create_project
from jira_mcp.models import CreateProjectRequest


class _Resp:
    def __init__(self, status_code: int = 200, json_data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict:
        return self._json

    def raise_for_status(self) -> None:
        if not self.ok:
            raise AssertionError(f"HTTP {self.status_code}: {self.text}")


class _StubJira:
    def __init__(self, base: str):
        self._base = base.rstrip("/")
        self._session = SimpleNamespace(get=self._get, post=self._post)

    def _get_url(self, path: str) -> str:
        # Emulate python-jira URL builder
        return f"{self._base}/rest/api/3/{path}" if not path.startswith("agile/") else f"{self._base}/rest/{path}"

    def _post(self, url: str, json: dict):  # noqa: A002 - shadowing json is fine in tests
        if url.endswith("/rest/api/3/project"):
            return _Resp(
                201,
                {
                    "id": "10001",
                    "key": json["key"],
                    "self": url + "/10001",
                },
            )
        return _Resp(404, text="not found")

    def _get(self, url: str, params: dict | None = None, headers: dict | None = None):
        if url.endswith("/rest/agile/1.0/board"):
            return _Resp(200, {"values": [{"id": 1234}]})
        return _Resp(200, {})


@pytest.fixture(autouse=True)
def _jira_base_env(monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", "https://acme.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "bot@acme.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "x")


def test_create_project_defaults_team_managed_and_returns_urls(monkeypatch):
    from jira_mcp import server as srv

    monkeypatch.setattr(srv, "_jira_client", lambda: _StubJira(os.environ["JIRA_BASE_URL"]))
    # Avoid actually calling add_project_admin for this test
    monkeypatch.setattr(
        srv,
        "add_project_admin",
        lambda request: {"added": True, "projectKey": request.projectKey},
    )

    req = CreateProjectRequest(
        name="Example",
        key="EX",
        projectTypeKey="software",
        managementStyle="team",
        requesterEmail="owner@acme.com",
    )

    res = create_project(req)

    assert res["projectKey"] == "EX"
    assert res["managementStyle"] == "team"
    assert res["projectTypeKey"] == "software"
    assert res["projectTemplateKey"].startswith("com.pyxis.greenhopper.jira:gh-simplified-agility-")
    assert res["projectUrl"].startswith("https://acme.atlassian.net")
    assert "/jira/software/projects/EX/summary" in res["projectUrl"]
    assert "/jira/software/projects/EX/boards/1234" in res["boardUrl"]
    assert res["boardId"] == 1234
    assert res["requesterAddedAsAdmin"] is True


## Removed company-managed test because managementStyle is restricted to 'team' by schema

