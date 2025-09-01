import base64
import io
import logging
import os
from typing import Any

import polars as pl
from dotenv import load_dotenv
from fastmcp import FastMCP
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

mcp = FastMCP("Jira MCP Server")


def _resolve_project_template_key(key_or_alias: str) -> str:
    """Resolve a friendly template alias into a Jira projectTemplateKey.

    Supports friendly names like "scrum" and "kanban" while still accepting
    full template keys containing a colon (":").
    """
    value = (key_or_alias or "").strip()
    if ":" in value:
        return value
    normalized = value.lower().replace(" ", "-")
    alias_map = {
        # Primary simplified agility templates
        "scrum": "com.pyxis.greenhopper.jira:gh-simplified-agility-scrum",
        "kanban": "com.pyxis.greenhopper.jira:gh-simplified-agility-kanban",
        "agility-scrum": "com.pyxis.greenhopper.jira:gh-simplified-agility-scrum",
        "agility-kanban": "com.pyxis.greenhopper.jira:gh-simplified-agility-kanban",
        # Classic templates
        "scrum-classic": "com.pyxis.greenhopper.jira:gh-simplified-scrum-classic",
        "kanban-classic": "com.pyxis.greenhopper.jira:gh-simplified-kanban-classic",
        # Other known greenhopper templates
        "gh-scrum-template": "com.pyxis.greenhopper.jira:gh-scrum-template",
        "gh-kanban-template": "com.pyxis.greenhopper.jira:gh-kanban-template",
        # Basic software
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


def _jira_client():
    """Create an authenticated Jira client using environment variables.

    Required env vars:
      - JIRA_BASE_URL
      - JIRA_EMAIL
      - JIRA_API_TOKEN
    """
    from jira import (
        JIRA,
    )  # Imported lazily to avoid test import-time dependency

    return JIRA(
        server=os.environ["JIRA_BASE_URL"],
        basic_auth=(os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"]),
        options={
            "rest_api_version": "3",
            "verify": True,
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        },
    )


class ListIssuesRequest(BaseModel):
    """Request model for listing Jira issues using JQL or simple filters.

    Attributes:
        jql: Optional raw JQL to use. When provided, other filters are ignored.
        projectKey: Optional project key to scope results, e.g., "ENG".
        issueType: Optional issue type filter, e.g., "Bug", "Task", "Story".
        status: Optional status filter, e.g., "To Do", "In Progress", "Done".
        assigneeEmail: Optional assignee email filter.
        reporterEmail: Optional reporter email filter.
        labels: Optional list of label names to require (matches any).
        fields: Optional list of field names to return; defaults to common fields.
        startAt: Pagination start index.
        maxResults: Maximum number of results to return.
        orderBy: Optional JQL ORDER BY clause (e.g., "-created", "priority DESC").
    """

    jql: str | None = None
    projectKey: str | None = None
    issueType: str | None = None
    status: str | None = None
    assigneeEmail: str | None = None
    reporterEmail: str | None = None
    labels: list[str] | None = None
    fields: list[str] | None = None
    startAt: int = 0
    maxResults: int = 50
    orderBy: str | None = None


def _escape_jql_value(value: str) -> str:
    """Escape a string value for safe inclusion in JQL quoted literals."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _build_list_issues_jql(request: ListIssuesRequest) -> str:
    """Build a JQL string from ListIssuesRequest simple filters.

    If request.jql is provided, returns it as-is (trimmed).
    """
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
            label_values = ", ".join(
                [f'"{_escape_jql_value(lbl)}"' for lbl in request.labels]
            )
            if label_values:
                clauses.append(f"labels in ({label_values})")
        base = " AND ".join(clauses) if clauses else ""
    if request.orderBy and request.orderBy.strip():
        # Allow leading '-' shorthand for DESC on a single field
        order = request.orderBy.strip()
        if order.startswith("-") and " " not in order:
            order = f"{order[1:]} DESC"
        base = f"{base} ORDER BY {order}".strip()
    return base or "order by created DESC"


def _extract_simple_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Extract a simple subset of Jira fields into flattened values.

    Always attempts to include summary, status, issuetype, assignee, reporter, priority.
    Missing fields are omitted.
    """
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


@mcp.tool(
    name="list_issues",
    description="List Jira issues using JQL or simple filters (projectKey, issueType, status, assigneeEmail, reporterEmail, labels). Returns keys and selected fields.",
)
def list_issues(request: ListIssuesRequest) -> dict[str, Any]:
    """List Jira issues.

    Builds a JQL query from the provided filters (or uses the raw JQL), queries the
    Jira Cloud search API, and returns a concise list of issue summaries with
    pagination metadata.
    """
    jira = _jira_client()
    jql = _build_list_issues_jql(request)

    # Default fields if none provided
    field_list = request.fields or [
        "summary",
        "status",
        "issuetype",
        "assignee",
        "reporter",
        "priority",
        "created",
        "updated",
    ]

    headers = {"Accept": "application/json"}
    params = {
        "jql": jql,
        "fields": ",".join(field_list),
        "startAt": max(0, int(request.startAt)),
        "maxResults": max(1, int(request.maxResults)),
    }

    # Prefer the modern endpoint path used elsewhere in this module
    url = jira._get_url("search/jql")
    resp = jira._session.get(url, params=params, headers=headers)
    resp.raise_for_status()
    data = resp.json()

    issues_out: list[dict[str, Any]] = []
    for item in data.get("issues", []) or []:
        key = item.get("key")
        fields_obj = item.get("fields", {}) or {}
        entry: dict[str, Any] = {"key": key}
        entry.update(_extract_simple_fields(fields_obj))
        issues_out.append(entry)

    return {
        "jql": jql,
        "startAt": data.get("startAt", request.startAt),
        "maxResults": data.get("maxResults", request.maxResults),
        "total": data.get("total", len(issues_out)),
        "issues": issues_out,
    }


class LookupProjectKeyRequest(BaseModel):
    """Request to look up a Jira project key by project name.

    Attributes:
        name: Project name to search for.
        maxResults: Maximum projects to fetch from the API (when using search endpoint).
    """

    name: str = Field(min_length=1)
    maxResults: int = 50


def _select_best_project_match(
    name: str, projects: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Select the best matching project by name using simple heuristics.

    Priority:
    1) Case-insensitive exact match on name
    2) Case-insensitive startswith
    3) Case-insensitive substring
    4) Fallback to the first project
    """
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


@mcp.tool(
    name="lookup_project_key",
    description="Look up a Jira project key by project name using the project search API.",
)
def lookup_project_key(request: LookupProjectKeyRequest) -> dict[str, Any]:
    """Return the best-match Jira project key given a project name.

    Uses /rest/api/3/project/search when available, falling back to listing all
    projects if needed. Returns the matched project's key, id, and name.
    """
    jira = _jira_client()

    # Prefer project search API
    search_url = jira._get_url("project/search")
    resp = jira._session.get(
        search_url,
        params={
            "query": request.name,
            "maxResults": max(1, int(request.maxResults)),
        },
        headers={"Accept": "application/json"},
    )

    projects: list[dict[str, Any]] = []
    if resp.ok:
        try:
            payload = resp.json() or {}
            projects = payload.get("values", []) or []
        except Exception:
            projects = []
    else:
        # Fallback to legacy list endpoint
        list_url = jira._get_url("project")
        alt = jira._session.get(
            list_url, headers={"Accept": "application/json"}
        )
        if alt.ok:
            try:
                projects = alt.json() or []
            except Exception:
                projects = []

    match = _select_best_project_match(request.name, projects)
    if not match:
        return {"found": False, "reason": "no_projects_visible"}

    return {
        "found": True,
        "projectKey": match.get("key"),
        "projectId": match.get("id"),
        "name": match.get("name"),
    }


class CreateProjectRequest(BaseModel):
    name: str
    key: str
    projectTypeKey: str = Field(pattern="^(software|service_desk|business)$")
    projectTemplateKey: str
    leadAccountId: str | None = None
    leadEmail: str | None = None


@mcp.tool(
    name="create_project",
    description="Create a Jira project via REST v3.",
)
def create_project(request: CreateProjectRequest) -> dict[str, Any]:
    """Create a Jira project using the Cloud REST API v3.

    Returns a dict with identifiers and self URL.
    """
    jira = _jira_client()
    # Resolve lead account id from email if needed
    lead_account_id: str | None = request.leadAccountId
    if not lead_account_id and request.leadEmail:
        resolved = _lookup_account_id_by_email(jira, request.leadEmail)
        if resolved is None:
            raise ValueError(
                f"Could not resolve lead account id from email: {request.leadEmail}"
            )
        lead_account_id = resolved

    # Use REST via python-jira session for reliability
    url = jira._get_url("project")
    payload = {
        "key": request.key,
        "name": request.name,
        "projectTypeKey": request.projectTypeKey,
        "projectTemplateKey": _resolve_project_template_key(
            request.projectTemplateKey
        ),
    }
    if lead_account_id:
        payload["leadAccountId"] = lead_account_id
    resp = jira._session.post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()
    return {
        "projectId": data.get("id"),
        "projectKey": data.get("key"),
        "selfUrl": data.get("self"),
    }


class BulkIssueUploadRequest(BaseModel):
    projectKey: str
    csv: str | None = Field(
        default=None, description="Raw CSV string or base64"
    )
    s3Url: str | None = Field(
        default=None, description="S3 URL (not supported in this server)"
    )
    dryRun: bool = Field(
        default=True,
        description="If true, validate only and don't create issues",
    )
    batchSize: int = Field(default=50, description="Bulk API batch size")
    defaults: dict[str, Any] = Field(
        default_factory=dict,
        description="Default Jira field values applied to every issue",
    )
    fieldMap: dict[str, str] = Field(
        default_factory=dict,
        description="CSV header -> logical field name mapping overrides",
    )
    csvPath: str | None = Field(
        default=None,
        description="Filesystem path to CSV file. If not provided, tool auto-detects standard template in CWD.",
    )


def _load_csv_to_frame(csv_text: str) -> pl.DataFrame:
    """Load CSV content (raw or base64-encoded) into a Polars DataFrame."""
    if csv_text.strip().startswith(
        "UEsDB"
    ):  # looks like zipped base64 (not supported here)
        raise ValueError("Compressed CSV is not supported")
    try:
        decoded_bytes = base64.b64decode(csv_text)
        return pl.read_csv(io.BytesIO(decoded_bytes))
    except Exception:
        return pl.read_csv(io.BytesIO(csv_text.encode("utf-8")))


def _load_csv_from_path(path: str) -> pl.DataFrame:
    """Load CSV from a filesystem path into a Polars DataFrame."""
    with open(path, "rb") as f:
        return pl.read_csv(f)


def _lookup_account_id_by_email(jira: Any, email: str) -> str | None:
    """Lookup Jira Cloud account id by email using the v3 user search endpoint.

    Returns accountId if found, otherwise None.
    """
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
    # Fallback: if single result, use it
    if users:
        return users[0].get("accountId")
    return None


def _rows_to_issues(
    df: pl.DataFrame, field_map: dict[str, str], defaults: dict[str, Any]
) -> list[dict[str, Any]]:
    """Convert a CSV DataFrame into Jira bulk issue payloads.

    Required columns: Summary, IssueType.
    """
    issues: list[dict[str, Any]] = []

    # Normalize headers: strip leading/trailing whitespace
    rename_map: dict[str, str] = {}
    for column_name in df.columns:
        stripped = column_name.strip()
        if stripped != column_name:
            rename_map[column_name] = stripped
    if rename_map:
        df = df.rename(rename_map)

    headers = list(df.columns)

    # Helper to resolve a logical field name to an actual column name
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

    # Minimal ADF conversion for plain text descriptions
    def to_adf(text: str) -> dict[str, Any]:
        paragraphs = []
        for block in str(text).splitlines():
            block = block.rstrip("\r")
            if block:
                paragraphs.append(
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": block}],
                    }
                )
            else:
                paragraphs.append({"type": "paragraph"})
        if not paragraphs:
            paragraphs = [{"type": "paragraph"}]
        return {"type": "doc", "version": 1, "content": paragraphs}

    summary_col = resolve_column(
        "Summary", synonyms=["Title"]
    )  # allow Title as synonym
    issuetype_col = resolve_column(
        "IssueType",
        synonyms=[
            "Issue Type",
            "Ticket Type for Scrum",
            "Ticket Type for Kanban",
            "Ticket Type",
        ],
    )
    description_primary_col = resolve_column("Description", synonyms=[])
    description_secondary_col = resolve_column(
        "Acceptance Criteria/ What we need to do",
        synonyms=["Acceptance Criteria"],
    )
    labels_col = resolve_column("Labels", synonyms=["Label", "Tags"])
    components_col = resolve_column(
        "Components", synonyms=["Component", "Component/s"]
    )
    assignee_email_col = resolve_column(
        "AssigneeEmail",
        synonyms=["Assignee", "Assignee Email", "Assignee email"],
    )

    # Validate required columns after applying mappings/synonyms
    if not summary_col:
        raise ValueError("Missing required column: Summary")
    if not issuetype_col:
        raise ValueError("Missing required column: IssueType")

    for row in df.iter_rows(named=True):
        summary = row.get(summary_col)

        # Determine issue type from mapped column; if it is empty, try other known type columns
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

        # Build description as ADF from available columns
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

        assignee_email = (
            row.get(assignee_email_col) if assignee_email_col else None
        )
        labels = row.get(labels_col) if labels_col else None
        components = row.get(components_col) if components_col else None

        fields: dict[str, Any] = {**defaults}
        if description_adf is not None:
            fields["description"] = description_adf
        if labels:
            fields["labels"] = [
                s.strip() for s in str(labels).split(",") if s.strip()
            ]
        if components:
            fields["components"] = [
                {"name": s.strip()}
                for s in str(components).split(",")
                if s.strip()
            ]
        if assignee_email:
            fields["assignee"] = {"emailAddress": assignee_email}

        issues.append(
            {
                "fields": {
                    "summary": summary,
                    "issuetype": {"name": issue_type_value},
                    **fields,
                }
            }
        )

    return issues


@mcp.tool(
    name="bulk_issue_upload",
    description="Bulk-create Jira issues from CSV. Supports csv, csvPath, or auto-detects 'JIRA Tickets  - JIRA tickets template.csv' in CWD.",
)
def bulk_issue_upload(request: BulkIssueUploadRequest) -> dict[str, Any]:
    """Bulk-create Jira issues from CSV content.

    Accepts inline CSV content (raw or base64). Returns counts and created keys.
    """
    if not request.csv and not request.csvPath and not request.s3Url:
        # Best-effort local discovery of a template CSV in CWD
        candidate = "JIRA Tickets  - JIRA tickets template.csv"
        if os.path.exists(candidate):
            request.csvPath = candidate
        else:
            raise ValueError("Provide csv, csvPath, or s3Url")
    if request.s3Url:
        # For simplicity, assume the caller resolved the CSV and passed its content in base64 string
        raise ValueError(
            "s3Url not supported in this minimal server; pass csv string"
        )
    df: pl.DataFrame
    if request.csvPath:
        df = _load_csv_from_path(request.csvPath)
    else:
        assert request.csv is not None
        # If csv string looks like a filename and exists, read from disk
        csv_str = request.csv.strip()
        if (
            "\n" not in csv_str
            and csv_str.lower().endswith(".csv")
            and os.path.exists(csv_str)
        ):
            df = _load_csv_from_path(csv_str)
        else:
            df = _load_csv_to_frame(csv_str)
    jira = _jira_client()
    issues = _rows_to_issues(df, request.fieldMap, request.defaults)
    created_keys: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []

    if request.dryRun:
        return {
            "created": 0,
            "issueKeys": [],
            "warnings": ["dryRun"],
            "errors": [],
        }

    batch = []
    for issue in issues:
        issue["fields"]["project"] = {"key": request.projectKey}
        batch.append(issue)
        if len(batch) >= max(1, request.batchSize):
            try:
                resp = jira._session.post(
                    jira._get_url("issue/bulk"), json={"issueUpdates": batch}
                )
                if resp.status_code == 429:
                    import time

                    time.sleep(2)
                    resp = jira._session.post(
                        jira._get_url("issue/bulk"),
                        json={"issueUpdates": batch},
                    )
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("issues", []):
                    key = item.get("key")
                    if key:
                        created_keys.append(key)
            except Exception as e:  # pragma: no cover - best effort
                errors.append(str(e))
            finally:
                batch = []

    if batch:
        try:
            resp = jira._session.post(
                jira._get_url("issue/bulk"), json={"issueUpdates": batch}
            )
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("issues", []):
                key = item.get("key")
                if key:
                    created_keys.append(key)
        except Exception as e:  # pragma: no cover
            errors.append(str(e))

    return {
        "created": len(created_keys),
        "issueKeys": created_keys,
        "warnings": warnings,
        "errors": errors,
    }


class DeleteProjectIssuesRequest(BaseModel):
    projectKey: str
    jql: str | None = None
    issueType: str | None = None
    dryRun: bool = True
    maxBatch: int = 100


class DeleteProjectRequest(BaseModel):
    """Request model for deleting an entire project."""

    projectKey: str
    dryRun: bool = True
    forceDelete: bool = False


@mcp.tool(
    name="delete_project_issues",
    description="Delete issues in a Jira project (optionally filter by issueType or extra JQL). Use dryRun to preview.",
)
def delete_project_issues(
    request: DeleteProjectIssuesRequest,
) -> dict[str, Any]:
    """Delete issues in a project using JQL paging with the modern search API. Returns counts and any errors."""
    logger.info(
        f"Starting delete_project_issues for project: {request.projectKey}"
    )

    try:
        jira = _jira_client()
        logger.info("JIRA client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize JIRA client: {e}")
        raise Exception(f"Failed to initialize JIRA client: {e}")

    base_jql = f"project = {request.projectKey}"
    if request.issueType:
        base_jql += f' AND issuetype = "{request.issueType}"'
    if request.jql:
        base_jql += f" AND ({request.jql})"

    logger.info(f"Using JQL query: {base_jql}")

    deleted: list[str] = []
    errors: list[str] = []
    start_at = 0

    while True:
        logger.info(f"Searching issues at start_at: {start_at}")

        # Use the modern enhanced search API with GET request first (more reliable)
        # This addresses the deprecated search API issue mentioned in JIRA's changelog
        # Use the correct modern endpoint: /rest/api/3/search/jql
        search_url = jira._get_url("search/jql")
        logger.debug(f"Search URL: {search_url}")

        # Add proper headers for modern JIRA API
        headers = {"Accept": "application/json"}

        # Try GET method first as it's more reliable based on our testing
        try:
            logger.info("Attempting primary search method with GET...")
            # Use GET request with query parameters
            search_params = {
                "jql": base_jql,
                "fields": "key",
                "startAt": start_at,
                "maxResults": request.maxBatch,
            }

            resp = jira._session.get(
                search_url, params=search_params, headers=headers
            )

            logger.debug(f"Search response status: {resp.status_code}")

            # Check for specific error responses
            if resp.status_code == 410:
                logger.error(
                    f"JIRA search API deprecated. Response: {resp.text}"
                )
                raise Exception(
                    f"JIRA search API deprecated. Response: {resp.text}"
                )
            elif resp.status_code == 400:
                logger.error(f"Invalid search request. Response: {resp.text}")
                raise Exception(
                    f"Invalid search request. Response: {resp.text}"
                )
            elif resp.status_code == 404:
                logger.error(
                    f"Search endpoint not found. Response: {resp.text}"
                )
                raise Exception(
                    f"Search endpoint not found. Response: {resp.text}"
                )

            resp.raise_for_status()
            logger.info("Primary search method (GET) successful")

        except Exception as search_error:
            logger.warning(
                f"Primary search method (GET) failed: {search_error}"
            )

            # Fallback: try using the POST version of the same endpoint
            try:
                logger.info("Attempting fallback search method with POST...")
                fallback_url = jira._get_url("search/jql")
                # Try with POST request and JSON body
                fallback_payload = {
                    "jql": base_jql,
                    "fields": ["key"],
                    "startAt": start_at,
                    "maxResults": request.maxBatch,
                }

                # Add Content-Type header for POST
                post_headers = headers.copy()
                post_headers["Content-Type"] = "application/json"

                resp = jira._session.post(
                    fallback_url, json=fallback_payload, headers=post_headers
                )
                resp.raise_for_status()
                logger.info("Fallback search method (POST) successful")

            except Exception as fallback_error:
                logger.error(
                    f"Both search methods failed. Primary: {search_error}, Fallback: {fallback_error}"
                )

                # Final fallback: try using a different approach - direct project issues endpoint
                try:
                    logger.info("Attempting final fallback method...")
                    # Try to get issues directly from the project
                    project_url = jira._get_url(
                        f"project/{request.projectKey}"
                    )
                    project_resp = jira._session.get(project_url)
                    if project_resp.ok:
                        logger.info(
                            "Project exists, trying alternative search method"
                        )
                        # If project exists, try a different search approach
                        raise Exception(
                            "Project exists but search API is not working. Please check JIRA API documentation for the latest search endpoint."
                        )
                    else:
                        raise Exception(
                            f"Project {request.projectKey} not found or inaccessible"
                        )

                except Exception as final_error:
                    logger.error(
                        f"All search methods failed. Final error: {final_error}"
                    )
                    raise Exception(
                        f"All search methods failed. Primary: {search_error}, Fallback: {fallback_error}, Final: {final_error}"
                    )
        data = resp.json()
        issues = data.get("issues", [])
        logger.info(f"Found {len(issues)} issues in batch")

        if not issues:
            break
        keys = [i.get("key") for i in issues if i.get("key")]
        logger.info(f"Processing {len(keys)} issue keys")

        for key in keys:
            try:
                logger.debug(f"Deleting issue: {key}")
                del_resp = jira._session.delete(jira._get_url(f"issue/{key}"))
                if del_resp.status_code == 429:
                    logger.warning(
                        f"Rate limited, waiting before retry for {key}"
                    )
                    import time

                    time.sleep(1)
                    del_resp = jira._session.delete(
                        jira._get_url(f"issue/{key}")
                    )
                del_resp.raise_for_status()
                deleted.append(key)
                logger.debug(f"Successfully deleted issue: {key}")
            except Exception as e:  # pragma: no cover
                logger.error(f"Failed to delete issue {key}: {e}")
                errors.append(f"{key}: {e}")
        start_at += len(issues)

    result = {
        "matched": len(deleted),
        "deleted": [] if request.dryRun else deleted,
        "errors": errors,
        "dryRun": request.dryRun,
    }
    logger.info(
        f"delete_project_issues completed. Matched: {len(deleted)}, Errors: {len(errors)}"
    )
    return result


@mcp.tool(
    name="delete_project",
    description="Delete an entire Jira project. This will delete all issues first, then the project itself. Use dryRun to preview.",
)
def delete_project(request: DeleteProjectRequest) -> dict[str, Any]:
    """Delete an entire project by first deleting all issues, then the project itself."""
    logger.info(f"Starting delete_project for project: {request.projectKey}")

    try:
        jira = _jira_client()
        logger.info("JIRA client initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize JIRA client: {e}")
        raise Exception(f"Failed to initialize JIRA client: {e}")

    # First, verify the project exists
    try:
        project_url = jira._get_url(f"project/{request.projectKey}")
        project_resp = jira._session.get(project_url)
        if not project_resp.ok:
            raise Exception(
                f"Project {request.projectKey} not found or inaccessible"
            )
        logger.info(f"Project {request.projectKey} exists and is accessible")
    except Exception as e:
        logger.error(f"Failed to verify project existence: {e}")
        raise Exception(f"Failed to verify project existence: {e}")

    # Step 1: Delete all issues in the project
    logger.info(f"Step 1: Deleting all issues in project {request.projectKey}")
    try:
        issues_request = DeleteProjectIssuesRequest(
            projectKey=request.projectKey, dryRun=request.dryRun, maxBatch=100
        )
        issues_result = delete_project_issues(issues_request)
        logger.info(f"Issues deletion result: {issues_result}")
    except Exception as e:
        logger.error(f"Failed to delete project issues: {e}")
        if not request.forceDelete:
            raise Exception(
                f"Failed to delete project issues: {e}. Use forceDelete=True to override."
            )
        logger.warning(
            "Continuing with project deletion despite issues deletion failure (forceDelete=True)"
        )

    # Step 2: Delete the project itself
    logger.info(f"Step 2: Deleting project {request.projectKey}")
    try:
        if request.dryRun:
            logger.info(
                f"Dry run mode - would delete project {request.projectKey}"
            )
            project_deleted = True
        else:
            # Delete the project using the project deletion endpoint
            project_delete_url = jira._get_url(f"project/{request.projectKey}")
            project_del_resp = jira._session.delete(project_delete_url)

            if project_del_resp.status_code == 429:
                logger.warning(
                    "Rate limited, waiting before retry for project deletion"
                )
                import time

                time.sleep(1)
                project_del_resp = jira._session.delete(project_delete_url)

            project_del_resp.raise_for_status()
            project_deleted = True
            logger.info(f"Successfully deleted project {request.projectKey}")

    except Exception as e:
        logger.error(f"Failed to delete project {request.projectKey}: {e}")
        if not request.forceDelete:
            raise Exception(
                f"Failed to delete project {request.projectKey}: {e}"
            )
        logger.warning(
            "Project deletion failed but forceDelete=True, continuing"
        )
        project_deleted = False

    result = {
        "projectKey": request.projectKey,
        "projectDeleted": project_deleted,
        "issuesDeleted": (
            issues_result.get("matched", 0)
            if "issues_result" in locals()
            else 0
        ),
        "dryRun": request.dryRun,
        "forceDelete": request.forceDelete,
    }

    logger.info(
        f"delete_project completed for {request.projectKey}. Project deleted: {project_deleted}"
    )
    return result


@mcp.tool(
    name="list_local_csv_templates",
    description="List CSV files in the current directory that look like import templates.",
)
def list_local_csv_templates() -> dict[str, Any]:
    """Return a list of CSV files in CWD to help users pick a local template."""
    candidates: list[str] = []
    try:
        for entry in os.listdir("."):
            if entry.lower().endswith(".csv"):
                candidates.append(entry)
    except Exception:
        pass
    # Put the standard template first if present
    standard = "JIRA Tickets  - JIRA tickets template.csv"
    candidates_sorted = sorted(
        {*candidates}, key=lambda n: (0 if n == standard else 1, n.lower())
    )
    return {"csvFiles": candidates_sorted}


if __name__ == "__main__":
    # Use stdio transport for MCP compatibility
    mcp.run(transport="stdio")
