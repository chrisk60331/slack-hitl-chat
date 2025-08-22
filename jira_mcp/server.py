import base64
import io
import os
from typing import Any, Dict, List, Optional

import polars as pl
from fastmcp import FastMCP
from pydantic import BaseModel, Field

from dotenv import load_dotenv

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
    from jira import JIRA  # Imported lazily to avoid test import-time dependency

    return JIRA(
        server=os.environ["JIRA_BASE_URL"],
        basic_auth=(os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"]),
        options={"rest_api_version": "3"},
    )


class CreateProjectRequest(BaseModel):
    name: str
    key: str
    projectTypeKey: str = Field(pattern="^(software|service_desk|business)$")
    projectTemplateKey: str
    leadAccountId: Optional[str] = None
    leadEmail: Optional[str] = None


@mcp.tool(
    name="create_project",
    description="Create a Jira project via REST v3.",
)
def create_project(request: CreateProjectRequest) -> Dict[str, Any]:
    """Create a Jira project using the Cloud REST API v3.

    Returns a dict with identifiers and self URL.
    """
    jira = _jira_client()
    # Resolve lead account id from email if needed
    lead_account_id: Optional[str] = request.leadAccountId
    if not lead_account_id and request.leadEmail:
        resolved = _lookup_account_id_by_email(jira, request.leadEmail)
        if resolved is None:
            raise ValueError(f"Could not resolve lead account id from email: {request.leadEmail}")
        lead_account_id = resolved

    # Use REST via python-jira session for reliability
    url = jira._get_url("project")
    payload = {
        "key": request.key,
        "name": request.name,
        "projectTypeKey": request.projectTypeKey,
        "projectTemplateKey": _resolve_project_template_key(request.projectTemplateKey),
    }
    if lead_account_id:
        payload["leadAccountId"] = lead_account_id
    resp = jira._session.post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()
    return {"projectId": data.get("id"), "projectKey": data.get("key"), "selfUrl": data.get("self")}


class BulkIssueUploadRequest(BaseModel):
    projectKey: str
    csv: Optional[str] = Field(default=None, description="Raw CSV string or base64")
    s3Url: Optional[str] = Field(default=None, description="S3 URL (not supported in this server)")
    dryRun: bool = Field(default=False, description="If true, validate only and don't create issues")
    batchSize: int = Field(default=50, description="Bulk API batch size")
    defaults: Dict[str, Any] = Field(default_factory=dict, description="Default Jira field values applied to every issue")
    fieldMap: Dict[str, str] = Field(default_factory=dict, description="CSV header -> logical field name mapping overrides")
    csvPath: Optional[str] = Field(default=None, description="Filesystem path to CSV file. If not provided, tool auto-detects standard template in CWD.")


def _load_csv_to_frame(csv_text: str) -> pl.DataFrame:
    """Load CSV content (raw or base64-encoded) into a Polars DataFrame."""
    if csv_text.strip().startswith("UEsDB"):  # looks like zipped base64 (not supported here)
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


def _lookup_account_id_by_email(jira: Any, email: str) -> Optional[str]:
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


def _rows_to_issues(df: pl.DataFrame, field_map: Dict[str, str], defaults: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert a CSV DataFrame into Jira bulk issue payloads.

    Required columns: Summary, IssueType.
    """
    issues: List[Dict[str, Any]] = []

    # Normalize headers: strip leading/trailing whitespace
    rename_map: Dict[str, str] = {}
    for column_name in df.columns:
        stripped = column_name.strip()
        if stripped != column_name:
            rename_map[column_name] = stripped
    if rename_map:
        df = df.rename(rename_map)

    headers = [c for c in df.columns]

    # Helper to resolve a logical field name to an actual column name
    def resolve_column(logical_name: str, synonyms: List[str]) -> Optional[str]:
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
    def to_adf(text: str) -> Dict[str, Any]:
        paragraphs = []
        for block in str(text).splitlines():
            block = block.rstrip("\r")
            if block:
                paragraphs.append({
                    "type": "paragraph",
                    "content": [{"type": "text", "text": block}]
                })
            else:
                paragraphs.append({"type": "paragraph"})
        if not paragraphs:
            paragraphs = [{"type": "paragraph"}]
        return {"type": "doc", "version": 1, "content": paragraphs}

    summary_col = resolve_column("Summary", synonyms=["Title"])  # allow Title as synonym
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
    components_col = resolve_column("Components", synonyms=["Component", "Component/s"])
    assignee_email_col = resolve_column("AssigneeEmail", synonyms=["Assignee", "Assignee Email", "Assignee email"])

    # Validate required columns after applying mappings/synonyms
    if not summary_col:
        raise ValueError("Missing required column: Summary")
    if not issuetype_col:
        raise ValueError("Missing required column: IssueType")

    for row in df.iter_rows(named=True):
        summary = row.get(summary_col)

        # Determine issue type from mapped column; if it is empty, try other known type columns
        issue_type_value: Optional[str] = None
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
        description_text_parts: List[str] = []
        if description_primary_col:
            v = row.get(description_primary_col)
            if v is not None and str(v).strip():
                description_text_parts.append(str(v).strip())
        if description_secondary_col:
            v = row.get(description_secondary_col)
            if v is not None and str(v).strip():
                description_text_parts.append(str(v).strip())
        description_adf: Optional[Dict[str, Any]] = None
        if description_text_parts:
            description_adf = to_adf("\n\n".join(description_text_parts))

        assignee_email = row.get(assignee_email_col) if assignee_email_col else None
        labels = row.get(labels_col) if labels_col else None
        components = row.get(components_col) if components_col else None

        fields: Dict[str, Any] = {**defaults}
        if description_adf is not None:
            fields["description"] = description_adf
        if labels:
            fields["labels"] = [s.strip() for s in str(labels).split(",") if s.strip()]
        if components:
            fields["components"] = [{"name": s.strip()} for s in str(components).split(",") if s.strip()]
        if assignee_email:
            fields["assignee"] = {"emailAddress": assignee_email}

        issues.append({
            "fields": {
                "summary": summary,
                "issuetype": {"name": issue_type_value},
                **fields,
            }
        })

    return issues


@mcp.tool(
    name="bulk_issue_upload",
    description="Bulk-create Jira issues from CSV. Supports csv, csvPath, or auto-detects 'JIRA Tickets  - JIRA tickets template.csv' in CWD.",
)
def bulk_issue_upload(request: BulkIssueUploadRequest) -> Dict[str, Any]:
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
        raise ValueError("s3Url not supported in this minimal server; pass csv string")
    df: pl.DataFrame
    if request.csvPath:
        df = _load_csv_from_path(request.csvPath)
    else:
        assert request.csv is not None
        # If csv string looks like a filename and exists, read from disk
        csv_str = request.csv.strip()
        if "\n" not in csv_str and csv_str.lower().endswith(".csv") and os.path.exists(csv_str):
            df = _load_csv_from_path(csv_str)
        else:
            df = _load_csv_to_frame(csv_str)
    jira = _jira_client()
    issues = _rows_to_issues(df, request.fieldMap, request.defaults)
    created_keys: List[str] = []
    errors: List[str] = []
    warnings: List[str] = []

    if request.dryRun:
        return {"created": 0, "issueKeys": [], "warnings": ["dryRun"], "errors": []}

    batch = []
    for issue in issues:
        issue["fields"]["project"] = {"key": request.projectKey}
        batch.append(issue)
        if len(batch) >= max(1, request.batchSize):
            try:
                resp = jira._session.post(jira._get_url("issue/bulk"), json={"issueUpdates": batch})
                if resp.status_code == 429:
                    import time
                    time.sleep(2)
                    resp = jira._session.post(jira._get_url("issue/bulk"), json={"issueUpdates": batch})
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
            resp = jira._session.post(jira._get_url("issue/bulk"), json={"issueUpdates": batch})
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("issues", []):
                key = item.get("key")
                if key:
                    created_keys.append(key)
        except Exception as e:  # pragma: no cover
            errors.append(str(e))

    return {"created": len(created_keys), "issueKeys": created_keys, "warnings": warnings, "errors": errors}


class DeleteProjectIssuesRequest(BaseModel):
    projectKey: str
    jql: Optional[str] = None
    issueType: Optional[str] = None
    dryRun: bool = True
    maxBatch: int = 100


@mcp.tool(
    name="delete_project_issues",
    description="Delete issues in a Jira project (optionally filter by issueType or extra JQL). Use dryRun to preview.",
)
def delete_project_issues(request: DeleteProjectIssuesRequest) -> Dict[str, Any]:
    """Delete issues in a project using JQL paging. Returns counts and any errors."""
    jira = _jira_client()
    base_jql = f"project = {request.projectKey}"
    if request.issueType:
        base_jql += f" AND issuetype = \"{request.issueType}\""
    if request.jql:
        base_jql += f" AND ({request.jql})"

    deleted: List[str] = []
    errors: List[str] = []
    start_at = 0
    while True:
        search_url = jira._get_url("search")
        resp = jira._session.get(
            search_url,
            params={
                "jql": base_jql,
                "fields": "key",
                "startAt": start_at,
                "maxResults": request.maxBatch,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        issues = data.get("issues", [])
        if not issues:
            break
        keys = [i.get("key") for i in issues if i.get("key")]
        if request.dryRun:
            deleted.extend(keys)
        else:
            for key in keys:
                try:
                    del_resp = jira._session.delete(jira._get_url(f"issue/{key}"))
                    if del_resp.status_code == 429:
                        import time
                        time.sleep(1)
                        del_resp = jira._session.delete(jira._get_url(f"issue/{key}"))
                    del_resp.raise_for_status()
                    deleted.append(key)
                except Exception as e:  # pragma: no cover
                    errors.append(f"{key}: {e}")
        start_at += len(issues)

    return {"matched": len(deleted), "deleted": [] if request.dryRun else deleted, "errors": errors, "dryRun": request.dryRun}


@mcp.tool(
    name="list_local_csv_templates",
    description="List CSV files in the current directory that look like import templates.",
)
def list_local_csv_templates() -> Dict[str, Any]:
    """Return a list of CSV files in CWD to help users pick a local template."""
    candidates: List[str] = []
    try:
        for entry in os.listdir('.'):
            if entry.lower().endswith('.csv'):
                candidates.append(entry)
    except Exception:
        pass
    # Put the standard template first if present
    standard = "JIRA Tickets  - JIRA tickets template.csv"
    candidates_sorted = sorted({*candidates}, key=lambda n: (0 if n == standard else 1, n.lower()))
    return {"csvFiles": candidates_sorted}


if __name__ == "__main__":
    # Use stdio transport for MCP compatibility
    mcp.run(transport="stdio")


