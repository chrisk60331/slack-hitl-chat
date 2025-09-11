from typing import Any

from pydantic import BaseModel, Field


class ListIssuesRequest(BaseModel):
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


class LookupProjectKeyRequest(BaseModel):
    name: str = Field(min_length=1)
    maxResults: int = 50


class CreateProjectRequest(BaseModel):
    name: str
    key: str
    projectTypeKey: str = Field(pattern="^(software|service_desk|business)$")
    # If omitted, defaults to a team-managed template based on managementStyle
    projectTemplateKey: str | None = None
    # Choose team-managed (default) or company-managed behavior
    managementStyle: str = Field(default="team", pattern="^(team)$")
    # Auto-grant admin to this requester email after creation (if provided)
    requesterEmail: str | None = None
    leadAccountId: str | None = None
    leadEmail: str | None = None


class BulkIssueUploadRequest(BaseModel):
    projectKey: str
    csv: str | None = Field(default=None, description="Raw CSV string or base64")
    s3Url: str | None = Field(default=None, description="S3 URL (not supported)")
    dryRun: bool = Field(default=True, description="If true, validate only")
    batchSize: int = Field(default=50, description="Bulk API batch size")
    defaults: dict[str, Any] = Field(default_factory=dict, description="Default field values applied to every issue")
    fieldMap: dict[str, str] = Field(default_factory=dict, description="CSV header -> logical field name mapping overrides")
    csvPath: str | None = Field(default=None, description="Filesystem path to CSV file")


class DeleteProjectIssuesRequest(BaseModel):
    projectKey: str
    jql: str | None = None
    issueType: str | None = None
    dryRun: bool = True
    maxBatch: int = 100


class DeleteProjectRequest(BaseModel):
    projectKey: str
    dryRun: bool = True
    forceDelete: bool = False


class AddProjectAdminRequest(BaseModel):
    projectKey: str
    accountId: str | None = None
    email: str | None = None
    roleName: str | None = None


class ListProjectsRequest(BaseModel):
    """Request for listing Jira projects using the search API.

    Attributes:
        query: Optional text to filter projects by name or key.
        maxResults: Maximum number of projects to return.
    """

    query: str | None = None
    maxResults: int = 50


class FilterProjectsByUserRequest(BaseModel):
    """Filter projects to those where the user has a permission (default: BROWSE_PROJECTS)."""

    # email: str | None = None
    # accountId: str | None = None
    permission: str = "BROWSE_PROJECTS"
    query: str | None = None
    maxResults: int = 1000


