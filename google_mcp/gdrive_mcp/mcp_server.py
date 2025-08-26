"""Google Drive MCP Server.

This module provides an MCP server for Google Drive operations including
document search, creation, and management using FastMCP.
"""

import os
import sys

import dotenv
from fastmcp import FastMCP
from fastmcp.server.auth import BearerAuthProvider
from fastmcp.server.auth.providers.bearer import RSAKeyPair

# Add the google_mcp directory to the path for local development
current_dir = os.path.dirname(os.path.abspath(__file__))
google_mcp_dir = os.path.join(current_dir, "..")
sys.path.append(google_mcp_dir)

from gdrive_mcp.models import (
    CopyDocumentRequest,
    CreateDocumentRequest,
    DeleteDocumentRequest,
    GetDocumentRequest,
    ListCustomerFilesRequest,
    ListDrivesRequest,
    ListFoldersRequest,
    SearchDocumentsRequest,
    UpdateDocumentRequest,
)
from gdrive_mcp.service import GoogleDriveService

# Generate a new key pair for development/testing
key_pair = RSAKeyPair.generate()
dotenv.load_dotenv()
# Configure the auth provider with the public key (optional for stdio)
auth = BearerAuthProvider(
    public_key=key_pair.public_key,
    issuer="https://dev.example.com",
    audience="google_drive",
)

# Initialize MCP server
mcp = FastMCP(
    "Google Drive MCP Server",
    # auth=auth,  # Commented out for stdio transport
    dependencies=["gdrive_mcp@./gdrive_mcp"],
)

# Initialize service
drive_service = GoogleDriveService()


@mcp.tool(
    name="search_documents",
    description="Search for documents in Google Drive using various criteria.",
    tags=["documents", "search", "google drive"],
)
def search_documents(request: SearchDocumentsRequest) -> dict:
    """
    Search for documents in Google Drive.

    Args:
        request (SearchDocumentsRequest):
            query (str): Search query string.
            file_types (List[str], optional): List of file types to search for.
            owner (str, optional): Email of the document owner to filter by.
            max_results (int, optional): Maximum number of results to return.
            include_shared (bool, optional): Whether to include shared documents.

    Returns:
        dict: Search results with metadata and file information.
    """
    return drive_service.search_documents(request)


@mcp.tool(
    name="create_document",
    description="Create a new document in Google Drive.",
    tags=["documents", "create", "google drive"],
)
def create_document(request: CreateDocumentRequest) -> dict:
    """
    Create a new document in Google Drive.

    Args:
        request (CreateDocumentRequest):
            title (str): Title of the document.
            document_type (str): Type of document to create.
            parent_folder_id (str, optional): ID of the parent folder.
            content (str, optional): Initial content for the document.
            permissions (List[str], optional): List of email addresses to share with.

    Returns:
        dict: Created document details and confirmation message.
    """
    return drive_service.create_document(request)


@mcp.tool(
    name="get_document",
    description="Get detailed information about a specific document.",
    tags=["documents", "get", "google drive"],
)
def get_document(request: GetDocumentRequest) -> dict:
    """
    Get detailed information about a specific document.

    Args:
        request (GetDocumentRequest):
            document_id (str): Google Drive document ID.
            include_content (bool, optional): Whether to include document content.

    Returns:
        dict: Document metadata and optional content.
    """
    return drive_service.get_document(request)


@mcp.tool(
    name="update_document",
    description="Update an existing document in Google Drive.",
    tags=["documents", "update", "google drive"],
)
def update_document(
    document_id: str | None = None,
    title: str | None = None,
    content: str | None = None,
    permissions: list[str] | None = None,
    request: UpdateDocumentRequest | None = None,
) -> dict:
    """
    Update an existing document in Google Drive.

    Accepts either a structured request model ("request") or top-level parameters
    matching the tool schema. This makes the tool compatible with clients that
    send either payload shape.

    Returns:
        dict: Update operation result and confirmation message.
    """
    if request is None:
        if not document_id:
            raise ValueError("document_id is required")
        request = UpdateDocumentRequest(
            document_id=document_id,
            title=title,
            content=content,
            permissions=permissions,
        )

    return drive_service.update_document(request)


@mcp.tool(
    name="delete_document",
    description="Delete a document from Google Drive.",
    tags=["documents", "delete", "google drive"],
)
def delete_document(request: DeleteDocumentRequest) -> dict:
    """
    Delete a document from Google Drive.

    Args:
        request (DeleteDocumentRequest):
            document_id (str): Google Drive document ID.
            permanent (bool, optional): Whether to permanently delete or move to trash.

    Returns:
        dict: Deletion operation result and confirmation message.
    """
    return drive_service.delete_document(request)


@mcp.tool(
    name="list_folders",
    description="List folders in Google Drive.",
    tags=["folders", "list", "google drive"],
)
def list_folders(request: ListFoldersRequest) -> dict:
    """
    List folders in Google Drive.

    Args:
        request (ListFoldersRequest):
            parent_folder_id (str, optional): ID of the parent folder to list contents from.
            max_results (int, optional): Maximum number of results to return.
            include_shared (bool, optional): Whether to include shared folders.

    Returns:
        dict: List of folders with metadata.
    """
    return drive_service.list_folders(request)


@mcp.tool(
    name="list_drives",
    description="List shared drives accessible to the service account.",
    tags=["drives", "list", "google drive"],
)
def list_drives(request: ListDrivesRequest) -> dict:
    """
    List shared drives accessible to the service account.

    Args:
        request (ListDrivesRequest):
            query (str, optional): Optional name filter; matched with name contains when provided.
            max_results (int, optional): Maximum number of shared drives to return.

    Returns:
        dict: List of shared drives with metadata.
    """
    return drive_service.list_drives(request)


@mcp.tool(
    name="copy_document",
    description="Copy a document/file in Google Drive to an optional destination folder, optionally renaming it.",
    tags=["documents", "copy", "google drive"],
)
def copy_document(request: CopyDocumentRequest) -> dict:
    """
    Copy a document/file in Google Drive.

    Args:
        request (CopyDocumentRequest):
            source_document_id (str): ID of the source document to copy.
            new_title (str, optional): Optional new title for the copied document.
            destination_folder_id (str, optional): Optional destination folder ID.
            permissions (List[str], optional): List of email addresses to share with.

    Returns:
        dict: Copied document details and confirmation message.
    """
    return drive_service.copy_document(request)


@mcp.tool(
    name="list_customer_files",
    description="List files for a given customer by navigating the customer folder hierarchy (root -> letter -> customer)",
    tags=["customers", "folders", "list", "google drive"],
)
def list_customer_files(request: ListCustomerFilesRequest) -> dict:
    """
    List files for a given customer by navigating the customer folder hierarchy.

    Environment:
        - GDRIVE_CUSTOMER_FOLDER_ID (required): ID of the root customer folder.

    Args:
        request (ListCustomerFilesRequest):
            customer_name (str): Full customer name used as the folder name.
            recursive (bool, optional): Include files from all subfolders.
            max_results (int, optional): Maximum number of results to return.
            include_shared (bool, optional): Include files not owned by the service account.

    Returns:
        dict: Resolved customer folder ID and list of files with metadata.
    """
    return drive_service.list_customer_files(request)


# Generate test token for development
token = key_pair.create_token(
    subject="dev-user",
    issuer="https://dev.example.com",
    audience="google_drive",
    scopes=["read", "write"],
)


if __name__ == "__main__":
    print(f"Test Bearer token for dev: {token}\n")
    # Use stdio transport for MCP client compatibility
    mcp.run(transport="stdio")
