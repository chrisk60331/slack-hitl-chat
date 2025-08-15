import polars as pl

from jira_mcp.server import _rows_to_issues


def test_rows_to_issues_basic():
    df = pl.DataFrame({
        "Summary": ["Task A", "Task B"],
        "IssueType": ["Task", "Task"],
        "Description": ["Desc A", "Desc B"],
        "Labels": ["one,two", None],
    })
    issues = _rows_to_issues(df, {}, {})
    assert len(issues) == 2
    assert issues[0]["fields"]["summary"] == "Task A"
    assert issues[0]["fields"]["issuetype"]["name"] == "Task"
    assert issues[0]["fields"]["labels"] == ["one", "two"]


