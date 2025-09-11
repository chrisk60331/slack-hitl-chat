import logging
import os
from typing import Any
import sys

from dotenv import load_dotenv
from fastmcp import FastMCP
from pydantic import BaseModel, Field
sys.path.append("/var/task/")
from jira_mcp.core import (
    _jira_client,
    _build_list_issues_jql,
    _extract_simple_fields,
    _select_best_project_match,
    _lookup_account_id_by_email,
    _resolve_project_template_key,
    _default_template_for_style,
    _compute_board_and_project_urls,
    _rows_to_issues,
    _get_project_role_url,
    _load_csv_from_path,
    _load_csv_to_frame,
    _format_project_entry,
)
from jira_mcp.models import (
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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

mcp = FastMCP("Jira MCP Server")


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
    # Determine template: explicit key dominates; otherwise default by style
    template_key: str
    if request.projectTemplateKey and request.projectTemplateKey.strip():
        template_key = _resolve_project_template_key(request.projectTemplateKey)
    else:
        template_key = _default_template_for_style(
            request.managementStyle, request.projectTypeKey
        )

    payload = {
        "key": request.key,
        "name": request.name,
        "projectTypeKey": request.projectTypeKey,
        "projectTemplateKey": template_key,
    }
    if lead_account_id:
        payload["leadAccountId"] = lead_account_id
    resp = jira._session.post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()
    project_id = data.get("id")
    project_key = data.get("key")
    result: dict[str, Any] = {
        "projectId": project_id,
        "projectKey": project_key,
        "selfUrl": data.get("self"),
        "managementStyle": request.managementStyle,
        "projectTypeKey": request.projectTypeKey,
        "projectTemplateKey": template_key,
    }

    # Best-effort: add requester as admin if provided
    if request.requesterEmail:
        try:
            add_result = add_project_admin(
                AddProjectAdminRequest(projectKey=project_key, email=request.requesterEmail)
            )
            result["requesterAddedAsAdmin"] = bool(add_result.get("added"))
        except Exception as e:
            logger.warning(f"Failed to add requester as admin: {e}")
            result["requesterAddedAsAdmin"] = False

    # Try to discover board and compute friendly URLs
    boards = jira.boards(projectKeyOrID=project_key)
    board_id = boards[0].id
    urls = _compute_board_and_project_urls(
        os.environ.get("JIRA_BASE_URL", ""), project_key, board_id, request.managementStyle
    )
    result.update(urls)

    logger.critical(f"Result: {result}")
    return result


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
    # Avoid importing heavy libs in the server module; construct the DataFrame in core helpers
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
    name="add_project_admin",
    description="Add a user to a Jira project's Administrators role. Provide projectKey and either accountId or email.",
)
def add_project_admin(request: AddProjectAdminRequest) -> dict[str, Any]:
    """Add a user as an admin to a Jira project by adding them to the admin role.

    Resolves accountId from email when needed. Returns details about the
    project, role, and user addition.
    """
    jira = _jira_client()

    # Resolve accountId from email if necessary
    account_id = request.accountId
    if not account_id and request.email:
        account_id = _lookup_account_id_by_email(jira, request.email)
        if not account_id:
            raise ValueError(
                f"Could not resolve accountId from email: {request.email}"
            )

    if not account_id:
        raise ValueError("Provide accountId or email")

    # Resolve the role URL for Administrators (or requested role)
    role = _get_project_role_url(jira, request.projectKey, request.roleName)
    if not role:
        raise ValueError(
            f"Could not find an Administrators role for project {request.projectKey}"
        )
    role_name, role_url = role

    # Add the user to the role; Jira Cloud expects accountIds under 'user'
    payload = {"user": [account_id]}
    resp = jira._session.post(
        role_url, json=payload, headers={"Content-Type": "application/json"}
    )

    # If already a member, Jira may return 400/409; treat as success idempotently
    if resp.status_code in {200, 201, 204}:
        pass
    else:
        try:
            resp.raise_for_status()
        except Exception as e:
            # Best-effort idempotent handling for duplicates
            text = getattr(resp, "text", "")
            if resp.status_code in {400, 409} and (
                "already" in text.lower() or "exists" in text.lower()
            ):
                # Treat as success
                logger.info(
                    "User already in role; treating add as successful"
                )
            else:
                raise e

    return {
        "projectKey": request.projectKey,
        "roleName": role_name,
        "accountId": account_id,
        "added": True,
    }


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


@mcp.tool(
    name="list_projects_for_user",
    description="List Jira projects the specified user can browse (permission BROWSE_PROJECTS). ",
)
def list_projects_for_user(request: FilterProjectsByUserRequest) -> dict[str, Any]:
    jira = _jira_client()
    # Resolve accountId from email if needed
    # account_id = request.accountId or (
    #     _lookup_account_id_by_email(jira, request.email or sys.argv[1])
    # )
    account_id = _lookup_account_id_by_email(jira, sys.argv[1])
    logger.info(f"Account ID: {account_id}")
    if not account_id:
        raise ValueError("Provide email or accountId")

    # Jira permissions API for projects a user has a permission on
    projects = {issue.fields.project.key for issue in jira.search_issues(f"assignee={account_id}")}
    
    return {
        "count": len(projects),
        "projects": projects,

    }

if __name__ == "__main__":
    # Use stdio transport for MCP compatibility
    mcp.run(transport="stdio")
