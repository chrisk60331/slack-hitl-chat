from jira_mcp.core import _format_project_entry


def test_format_project_entry_minimal_and_with_lead():
    raw = {"id": "10000", "key": "ENG", "name": "Engineering", "projectTypeKey": "software"}
    out = _format_project_entry(raw)
    assert out == {
        "id": "10000",
        "key": "ENG",
        "name": "Engineering",
        "projectTypeKey": "software",
        "lead": None,
    }

    raw2 = {
        "id": "10001",
        "key": "OPS",
        "name": "Operations",
        "projectTypeKey": "business",
        "lead": {"displayName": "Alice"},
    }
    out2 = _format_project_entry(raw2)
    assert out2["lead"] == "Alice"

