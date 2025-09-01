from jira_mcp.server import _select_best_project_match


def test_select_best_project_match_priority_exact_then_startswith_then_contains():
    projects = [
        {"key": "APP", "name": "App Platform"},
        {"key": "ENG", "name": "Engineering"},
        {"key": "APX", "name": "App eXperience"},
    ]

    # Exact match
    m = _select_best_project_match("Engineering", projects)
    assert m and m["key"] == "ENG"

    # Startswith match when no exact
    m = _select_best_project_match("App", projects)
    assert m and m["key"] in {"APP", "APX"}

    # Contains match when no exact/startswith
    m = _select_best_project_match("xper", projects)
    assert m and m["key"] == "APX"

    # Fallback to first when nothing matches
    m = _select_best_project_match("Nonexistent", projects)
    assert m and m["key"] == "APP"
