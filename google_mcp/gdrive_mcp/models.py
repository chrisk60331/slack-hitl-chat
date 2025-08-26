"""Pydantic models for Google Drive MCP operations.

This module defines request schemas for Google Drive operations using Pydantic v2.
It includes models for document search, creation, and management operations.
"""

from pydantic import BaseModel, Field


class SearchDocumentsRequest(BaseModel):
    """Request model for searching documents in Google Drive."""

    query: str = Field(..., description="Search query string")
    file_types: list[str] | None = Field(
        None,
        description="List of file types to search for (e.g., ['document', 'spreadsheet', 'presentation'])",
    )
    owner: str | None = Field(
        None, description="Email of the document owner to filter by"
    )
    max_results: int | None = Field(
        10, description="Maximum number of results to return"
    )
    include_shared: bool | None = Field(
        True, description="Whether to include shared documents"
    )


class CreateDocumentRequest(BaseModel):
    """Request model for creating documents in Google Drive."""

    title: str = Field(..., description="Title of the document")
    document_type: str = Field(
        ...,
        description="Type of document to create: 'document', 'spreadsheet', 'presentation', 'folder'",
    )
    parent_folder_id: str | None = Field(
        None, description="ID of the parent folder to create the document in"
    )
    content: str | None = Field(
        None,
        description="Initial content for the document (for text-based documents)",
    )
    permissions: list[str] | None = Field(
        None, description="List of email addresses to share the document with"
    )


class GetDocumentRequest(BaseModel):
    """Request model for retrieving document information."""

    document_id: str = Field(..., description="Google Drive document ID")
    include_content: bool | None = Field(
        False,
        description="Whether to include document content in the response",
    )


class UpdateDocumentRequest(BaseModel):
    """Request model for updating documents in Google Drive."""

    document_id: str = Field(..., description="Google Drive document ID")
    title: str | None = Field(None, description="New title for the document")
    content: str | None = Field(
        None, description="New content for the document"
    )
    permissions: list[str] | None = Field(
        None,
        description="List of email addresses to update sharing permissions with",
    )


class DeleteDocumentRequest(BaseModel):
    """Request model for deleting documents from Google Drive."""

    document_id: str = Field(..., description="Google Drive document ID")
    permanent: bool | None = Field(
        False,
        description="Whether to permanently delete (true) or move to trash (false)",
    )


class ListFoldersRequest(BaseModel):
    """Request model for listing folders in Google Drive."""

    parent_folder_id: str | None = Field(
        None, description="ID of the parent folder to list contents from"
    )
    max_results: int | None = Field(
        50, description="Maximum number of results to return"
    )
    include_shared: bool | None = Field(
        True, description="Whether to include shared folders"
    )


class ListDrivesRequest(BaseModel):
    """Request model for listing shared drives accessible to the service account."""

    query: str | None = Field(
        None,
        description="Optional name filter; matched with name contains when provided",
    )
    max_results: int | None = Field(
        50, description="Maximum number of shared drives to return"
    )
    requester_email: str | None = Field(
        None,
        description="Email address of the requester",
    )


class CopyDocumentRequest(BaseModel):
    """Request model for copying a document/file in Google Drive."""

    source_document_id: str = Field(
        ..., description="ID of the source document to copy"
    )
    new_title: str | None = Field(
        None, description="Optional new title for the copied document"
    )
    destination_folder_id: str | None = Field(
        None,
        description="Optional destination folder ID for the copied document",
    )
    permissions: list[str] | None = Field(
        None,
        description="Optional list of email addresses to share the copied document with",
    )


class ListCustomerFilesRequest(BaseModel):
    """Request model for listing files by customer folder.

    The Google Drive hierarchy is expected to be:
    - Root customer folder (env var `GDRIVE_CUSTOMER_FOLDER_ID`)
      - Letter folder (first letter of the customer name)
        - Customer folder (named exactly as the customer)
          - Files and subfolders
    """

    customer_name: str = Field(
        ..., description="Full customer name used as the folder name"
    )
    recursive: bool | None = Field(
        False,
        description="If true, include files from all subfolders recursively",
    )
    max_results: int | None = Field(
        100, description="Maximum number of results to return"
    )
    include_shared: bool | None = Field(
        True,
        description="Whether to include files not owned by the service account",
    )
