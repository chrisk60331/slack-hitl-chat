import polars as pl

from jira_mcp.core import _resolve_project_template_key, _rows_to_issues


def test_rows_to_issues_basic():
    df = pl.DataFrame(
        {
            "Summary": ["Task A", "Task B"],
            "IssueType": ["Task", "Task"],
            "Description": ["Desc A", "Desc B"],
            "Labels": ["one,two", None],
        }
    )
    issues = _rows_to_issues(df, {}, {})
    assert len(issues) == 2
    assert issues[0]["fields"]["summary"] == "Task A"
    assert issues[0]["fields"]["issuetype"]["name"] == "Task"
    assert issues[0]["fields"]["labels"] == ["one", "two"]
    # description must be ADF
    assert issues[0]["fields"]["description"]["type"] == "doc"
    assert issues[0]["fields"]["description"]["version"] == 1


def test_rows_to_issues_header_whitespace_and_ticket_type_aliases():
    # Headers contain trailing spaces and only Kanban/Scrum columns for type
    df = pl.DataFrame(
        {
            "Summary ": ["Story X"],
            "Ticket Type for Kanban": ["Task"],
            "Acceptance Criteria/ What we need to do": ["AC 1"],
            "Description": ["Body"],
        }
    )
    issues = _rows_to_issues(df, {}, {})
    assert len(issues) == 1
    fields = issues[0]["fields"]
    assert fields["summary"] == "Story X"
    assert fields["issuetype"]["name"] == "Task"
    # Description should combine Description + Acceptance Criteria as ADF
    desc = fields["description"]
    assert desc["type"] == "doc" and desc["version"] == 1
    text_blocks = [
        n.get("text")
        for p in desc["content"]
        for n in p.get("content", [])
        if n.get("type") == "text"
    ]
    assert "Body" in "\n".join(text_blocks) and "AC 1" in "\n".join(
        text_blocks
    )


def test_rows_to_issues_prefers_scrum_over_kanban_when_both_present():
    df = pl.DataFrame(
        {
            "Summary": ["Mixed Type"],
            "Ticket Type for Scrum": ["Story"],
            "Ticket Type for Kanban": ["Task"],
        }
    )
    issues = _rows_to_issues(df, {}, {})
    assert len(issues) == 1
    assert issues[0]["fields"]["issuetype"]["name"] == "Story"


def test_resolve_project_template_key_aliases():
    assert (
        _resolve_project_template_key("scrum")
        == "com.pyxis.greenhopper.jira:gh-simplified-agility-scrum"
    )
    assert (
        _resolve_project_template_key("kanban")
        == "com.pyxis.greenhopper.jira:gh-simplified-agility-kanban"
    )
    assert (
        _resolve_project_template_key("scrum-classic")
        == "com.pyxis.greenhopper.jira:gh-simplified-scrum-classic"
    )
    assert (
        _resolve_project_template_key("kanban-classic")
        == "com.pyxis.greenhopper.jira:gh-simplified-kanban-classic"
    )
    assert (
        _resolve_project_template_key("basic")
        == "com.pyxis.greenhopper.jira:gh-simplified-basic"
    )
    # Passthrough full keys
    full = "com.pyxis.greenhopper.jira:gh-simplified-agility-kanban"
    assert _resolve_project_template_key(full) == full
