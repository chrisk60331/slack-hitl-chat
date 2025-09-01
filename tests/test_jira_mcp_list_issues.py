from jira_mcp.server import (
    ListIssuesRequest,
    _build_list_issues_jql,
    _extract_simple_fields,
)


def test_build_list_issues_jql_simple_filters_and_order():
    req = ListIssuesRequest(
        projectKey="ENG",
        issueType="Bug",
        status="In Progress",
        assigneeEmail="user@example.com",
        labels=["urgent", "backend"],
        orderBy="-created",
    )
    jql = _build_list_issues_jql(req)
    # Contains all simple clauses
    assert "project = ENG" in jql
    assert 'issuetype = "Bug"' in jql
    assert 'status = "In Progress"' in jql
    assert 'assignee = "user@example.com"' in jql
    # labels
    assert 'labels in ("urgent", "backend")' in jql
    # order-by shorthand expanded
    assert jql.lower().endswith("order by created desc")


def test_build_list_issues_jql_uses_raw_when_provided_and_appends_order():
    req = ListIssuesRequest(
        jql='project = OPS AND status = "To Do"', orderBy="priority DESC"
    )
    jql = _build_list_issues_jql(req)
    assert jql.startswith('project = OPS AND status = "To Do"')
    assert jql.endswith("ORDER BY priority DESC")


def test_extract_simple_fields_flattening():
    fields = {
        "summary": "Fix login",
        "status": {"name": "In Progress"},
        "issuetype": {"name": "Bug"},
        "assignee": {
            "displayName": "Ada Developer",
            "emailAddress": "ada@example.com",
        },
        "reporter": {"displayName": "Bob Reporter"},
        "priority": {"name": "High"},
    }
    out = _extract_simple_fields(fields)
    assert out == {
        "summary": "Fix login",
        "status": "In Progress",
        "issuetype": "Bug",
        "assignee": "ada@example.com",
        "reporter": "Bob Reporter",
        "priority": "High",
    }
