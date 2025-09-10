from jira_mcp.core import _select_role_url


def test_select_role_url_exact_and_substring():
    roles = {
        "Users": "http://example/roles/10000",
        "Administrators": "http://example/roles/10001",
        "Developers": "http://example/roles/10002",
    }
    # Exact
    match = _select_role_url(roles, ["Administrators"])
    assert match == ("Administrators", roles["Administrators"])
    # Case-insensitive
    match = _select_role_url(roles, ["administrators"])  # lower
    assert match == ("Administrators", roles["Administrators"])
    # Substring fallback
    match = _select_role_url(roles, ["admin"])  # token
    assert match == ("Administrators", roles["Administrators"])
    # Not found returns None
    assert _select_role_url({}, ["Administrators"]) is None

