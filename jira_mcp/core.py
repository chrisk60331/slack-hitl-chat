import base64
import io
import os
from typing import Any

import polars as pl
from pydantic import BaseModel, Field
from .models import (
    ListIssuesRequest,
    LookupProjectKeyRequest,
    CreateProjectRequest,
    BulkIssueUploadRequest,
    DeleteProjectIssuesRequest,
    DeleteProjectRequest,
    AddProjectAdminRequest,
    ListProjectsRequest,
    FilterProjectsByUserRequest,
)


def _resolve_project_template_key(key_or_alias: str) -> str:
    """Resolve a friendly template alias into a Jira projectTemplateKey."""
    value = (key_or_alias or "").strip()
    if ":" in value:
        return value
    normalized = value.lower().replace(" ", "-")
    alias_map = {
        "scrum": "com.pyxis.greenhopper.jira:gh-simplified-agility-scrum",
        "kanban": "com.pyxis.greenhopper.jira:gh-simplified-agility-kanban",
        "agility-scrum": "com.pyxis.greenhopper.jira:gh-simplified-agility-scrum",
        "agility-kanban": "com.pyxis.greenhopper.jira:gh-simplified-agility-kanban",
        "scrum-classic": "com.pyxis.greenhopper.jira:gh-simplified-scrum-classic",
        "kanban-classic": "com.pyxis.greenhopper.jira:gh-simplified-kanban-classic",
        "gh-scrum-template": "com.pyxis.greenhopper.jira:gh-scrum-template",
        "gh-kanban-template": "com.pyxis.greenhopper.jira:gh-kanban-template",
        "basic": "com.pyxis.greenhopper.jira:gh-simplified-basic",
        "basic-software-development-template": "com.pyxis.greenhopper.jira:basic-software-development-template",
        "software-basic": "com.pyxis.greenhopper.jira:basic-software-development-template",
    }
    resolved = alias_map.get(normalized)
    if not resolved:
        supported = ", ".join(sorted(alias_map.keys()))
        raise ValueError(
            f"Unknown project template alias '{key_or_alias}'. Supported aliases: {supported}, or pass a full template key."
        )
    return resolved
def _default_template_for_style(style: str, project_type_key: str) -> str:
    """Return a default projectTemplateKey given a management style.

    For team-managed (default), prefer agility kanban. For company-managed, prefer classic kanban.
    """
    normalized_style = (style or "team").strip().lower()
    # Only software projects supported by defaults for now
    if project_type_key != "software":
        # Fall back to Jira's basic template choices
        return "com.pyxis.greenhopper.jira:gh-simplified-agility-kanban"
    if normalized_style == "company":
        return "com.pyxis.greenhopper.jira:gh-simplified-kanban-classic"
    return "com.pyxis.greenhopper.jira:gh-simplified-agility-kanban"


def _compute_board_and_project_urls(
    base_url: str, project_key: str, board_id: int | None, management_style: str
) -> dict[str, str | int | None]:
    """Compute friendly URLs for the project and board.

    Returns keys: projectUrl, boardUrl, boardId
    """
    base = base_url.rstrip("/")
    project_key_str = str(project_key)
    # Prefer the standard web UI URLs (no '/c' segment)
    project_url = f"{base}/jira/software/projects/{project_key_str}/summary"
    if board_id is not None:
        board_url = f"{base}/jira/software/projects/{project_key_str}/boards/{board_id}"
    else:
        board_url = f"{base}/jira/software/projects/{project_key_str}/boards"
    return {"projectUrl": project_url, "boardUrl": board_url, "boardId": board_id}



def _jira_client():
    """Create an authenticated Jira client using environment variables."""
    from jira import JIRA

    return JIRA(
        server=os.environ["JIRA_BASE_URL"],
        basic_auth=(os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"]),
        options={
            "rest_api_version": "3",
            "verify": True,
            "headers": {"Accept": "application/json", "Content-Type": "application/json"},
        },
    )


 


def _escape_jql_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _build_list_issues_jql(request: ListIssuesRequest) -> str:
    if request.jql and request.jql.strip():
        base = request.jql.strip()
    else:
        clauses: list[str] = []
        if request.projectKey:
            clauses.append(f"project = {request.projectKey}")
        if request.issueType:
            v = _escape_jql_value(request.issueType)
            clauses.append(f'issuetype = "{v}"')
        if request.status:
            v = _escape_jql_value(request.status)
            clauses.append(f'status = "{v}"')
        if request.assigneeEmail:
            v = _escape_jql_value(request.assigneeEmail)
            clauses.append(f'assignee = "{v}"')
        if request.reporterEmail:
            v = _escape_jql_value(request.reporterEmail)
            clauses.append(f'reporter = "{v}"')
        if request.labels:
            label_values = ", ".join([f'"{_escape_jql_value(lbl)}"' for lbl in request.labels])
            if label_values:
                clauses.append(f"labels in ({label_values})")
        base = " AND ".join(clauses) if clauses else ""
    if request.orderBy and request.orderBy.strip():
        order = request.orderBy.strip()
        if order.startswith("-") and " " not in order:
            order = f"{order[1:]} DESC"
        base = f"{base} ORDER BY {order}".strip()
    return base or "order by created DESC"


def _extract_simple_fields(fields: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "summary" in fields and fields["summary"] is not None:
        result["summary"] = fields["summary"]
    status = fields.get("status") or {}
    if isinstance(status, dict) and status.get("name"):
        result["status"] = status.get("name")
    issuetype = fields.get("issuetype") or {}
    if isinstance(issuetype, dict) and issuetype.get("name"):
        result["issuetype"] = issuetype.get("name")
    assignee = fields.get("assignee") or {}
    if isinstance(assignee, dict):
        email = assignee.get("emailAddress")
        display = assignee.get("displayName")
        if email or display:
            result["assignee"] = email or display
    reporter = fields.get("reporter") or {}
    if isinstance(reporter, dict):
        email = reporter.get("emailAddress")
        display = reporter.get("displayName")
        if email or display:
            result["reporter"] = email or display
    priority = fields.get("priority") or {}
    if isinstance(priority, dict) and priority.get("name"):
        result["priority"] = priority.get("name")
    return result


 


def _select_best_project_match(name: str, projects: list[dict[str, Any]]) -> dict[str, Any] | None:
    target = name.strip().lower()
    if not projects:
        return None

    def norm(n: str | None) -> str:
        return (n or "").strip().lower()

    exact = [p for p in projects if norm(p.get("name")) == target]
    if exact:
        return exact[0]
    starts = [p for p in projects if norm(p.get("name")).startswith(target)]
    if starts:
        return starts[0]
    contains = [p for p in projects if target in norm(p.get("name"))]
    if contains:
        return contains[0]
    return projects[0]


 


 


def _load_csv_to_frame(csv_text: str) -> pl.DataFrame:
    if csv_text.strip().startswith("UEsDB"):
        raise ValueError("Compressed CSV is not supported")
    try:
        decoded_bytes = base64.b64decode(csv_text)
        return pl.read_csv(io.BytesIO(decoded_bytes))
    except Exception:
        return pl.read_csv(io.BytesIO(csv_text.encode("utf-8")))


def _load_csv_from_path(path: str) -> pl.DataFrame:
    with open(path, "rb") as f:
        return pl.read_csv(f)


def _lookup_account_id_by_email(jira: Any, email: str) -> str | None:
    url = jira._get_url("user/search")
    resp = jira._session.get(url, params={"query": email, "maxResults": 10})
    if not resp.ok:
        return None
    try:
        users = resp.json() or []
    except Exception:
        return None
    email_lower = email.lower()
    for user in users:
        if str(user.get("emailAddress", "")).lower() == email_lower:
            return user.get("accountId")
    if users:
        return users[0].get("accountId")
    return None


def _rows_to_issues(df: pl.DataFrame, field_map: dict[str, str], defaults: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    rename_map: dict[str, str] = {}
    for column_name in df.columns:
        stripped = column_name.strip()
        if stripped != column_name:
            rename_map[column_name] = stripped
    if rename_map:
        df = df.rename(rename_map)

    headers = list(df.columns)

    def resolve_column(logical_name: str, synonyms: list[str]) -> str | None:
        mapped = field_map.get(logical_name)
        if mapped and mapped in headers:
            return mapped
        if logical_name in headers:
            return logical_name
        for candidate in synonyms:
            if candidate in headers:
                return candidate
        return None

    def to_adf(text: str) -> dict[str, Any]:
        paragraphs = []
        for block in str(text).splitlines():
            block = block.rstrip("\r")
            if block:
                paragraphs.append({"type": "paragraph", "content": [{"type": "text", "text": block}]})
            else:
                paragraphs.append({"type": "paragraph"})
        if not paragraphs:
            paragraphs = [{"type": "paragraph"}]
        return {"type": "doc", "version": 1, "content": paragraphs}

    summary_col = resolve_column("Summary", synonyms=["Title"])
    issuetype_col = resolve_column(
        "IssueType",
        synonyms=["Issue Type", "Ticket Type for Scrum", "Ticket Type for Kanban", "Ticket Type"],
    )
    description_primary_col = resolve_column("Description", synonyms=[])
    description_secondary_col = resolve_column(
        "Acceptance Criteria/ What we need to do", synonyms=["Acceptance Criteria"]
    )
    labels_col = resolve_column("Labels", synonyms=["Label", "Tags"])
    components_col = resolve_column("Components", synonyms=["Component", "Component/s"])
    assignee_email_col = resolve_column("AssigneeEmail", synonyms=["Assignee", "Assignee Email", "Assignee email"])

    if not summary_col:
        raise ValueError("Missing required column: Summary")
    if not issuetype_col:
        raise ValueError("Missing required column: IssueType")

    for row in df.iter_rows(named=True):
        summary = row.get(summary_col)
        issue_type_value: str | None = None
        if issuetype_col:
            v = row.get(issuetype_col)
            if v is not None and str(v).strip():
                issue_type_value = str(v).strip()
        if not issue_type_value:
            for fallback_col in [
                "IssueType",
                "Issue Type",
                "Ticket Type for Scrum",
                "Ticket Type for Kanban",
                "Ticket Type",
            ]:
                if fallback_col in headers:
                    v = row.get(fallback_col)
                    if v is not None and str(v).strip():
                        issue_type_value = str(v).strip()
                        break

        description_text_parts: list[str] = []
        if description_primary_col:
            v = row.get(description_primary_col)
            if v is not None and str(v).strip():
                description_text_parts.append(str(v).strip())
        if description_secondary_col:
            v = row.get(description_secondary_col)
            if v is not None and str(v).strip():
                description_text_parts.append(str(v).strip())
        description_adf: dict[str, Any] | None = None
        if description_text_parts:
            description_adf = to_adf("\n\n".join(description_text_parts))

        assignee_email = row.get(assignee_email_col) if assignee_email_col else None
        labels = row.get(labels_col) if labels_col else None
        components = row.get(components_col) if components_col else None

        fields: dict[str, Any] = {**defaults}
        if description_adf is not None:
            fields["description"] = description_adf
        if labels:
            fields["labels"] = [s.strip() for s in str(labels).split(",") if s.strip()]
        if components:
            fields["components"] = [{"name": s.strip()} for s in str(components).split(",") if s.strip()]
        if assignee_email:
            fields["assignee"] = {"emailAddress": assignee_email}

        issues.append({"fields": {"summary": summary, "issuetype": {"name": issue_type_value}, **fields}})

    return issues
    

def _select_role_url(roles_map: dict[str, str], preferred_names: list[str]) -> tuple[str, str] | None:
    if not roles_map:
        return None
    lowered_to_name: dict[str, str] = {name.lower(): name for name in roles_map.keys()}
    for name in preferred_names:
        exact = lowered_to_name.get(name.lower())
        if exact:
            return exact, roles_map[exact]
    for name in preferred_names:
        token = name.lower()
        for candidate_lower, original_name in lowered_to_name.items():
            if token in candidate_lower:
                return original_name, roles_map[original_name]
    return None


def _get_project_role_url(jira: Any, project_key: str, role_name: str | None) -> tuple[str, str] | None:
    url = jira._get_url(f"project/{project_key}/role")
    resp = jira._session.get(url, headers={"Accept": "application/json"})
    resp.raise_for_status()
    roles_map: dict[str, str] = resp.json() or {}
    if role_name and role_name.strip():
        selected = _select_role_url(roles_map, [role_name])
        if selected:
            return selected
    preferred = [
        "Administrators",
        "Administrator",
        "Project Administrators",
        "Administrators project role",
        "Admin",
    ]
    return _select_role_url(roles_map, preferred)


# Lightweight normalizer for project objects coming from search/list endpoints
def _format_project_entry(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": p.get("id"),
        "key": p.get("key"),
        "name": p.get("name"),
        "projectTypeKey": p.get("projectTypeKey"),
        "lead": (p.get("lead") or {}).get("displayName") if isinstance(p.get("lead"), dict) else None,
    }


def _resolve_account_id(jira: Any, email: str | None, account_id: str | None) -> str | None:
    if account_id:
        return account_id
    if email:
        return _lookup_account_id_by_email(jira, email)
    return None

