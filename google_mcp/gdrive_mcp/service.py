"""Google Drive service for MCP operations.

This module provides high-level operations for Google Drive including
document search, creation, and management using the Google Drive API.
"""

import logging
import os
from typing import Any

import dotenv

from .drive_client import GoogleDriveClient
from .models import (
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

logger = logging.getLogger(__name__)
dotenv.load_dotenv()


class GoogleDriveService:
    """Service for managing Google Drive operations."""

    def __init__(self):
        """Initialize the Google Drive service."""
        logger.info("Initializing Google Drive service")
        self.client = GoogleDriveClient()

    def search_documents(
        self, request: SearchDocumentsRequest
    ) -> dict[str, Any]:
        """Search for documents in Google Drive.

        Args:
            request: SearchDocumentsRequest containing search parameters.

        Returns:
            Dict containing search results and metadata.
        """
        logger.info(f"Searching documents with query: {request.query}")

        try:
            # Build search query
            # Interpret free-text query using name/fullText contains per Drive v3
            text = request.query.strip()
            if text:
                # Escape single quotes in user text per Drive query syntax
                safe_text = text.replace("'", "\\'")
                text_clause = f"(name contains '{safe_text}' or fullText contains '{safe_text}')"
            else:
                text_clause = None

            query_parts = []
            if text_clause:
                query_parts.append(text_clause)

            if request.file_types:
                file_type_filters = []
                for file_type in request.file_types:
                    if file_type == "document":
                        file_type_filters.append(
                            "mimeType='application/vnd.google-apps.document'"
                        )
                    elif file_type == "spreadsheet":
                        file_type_filters.append(
                            "mimeType='application/vnd.google-apps.spreadsheet'"
                        )
                    elif file_type == "presentation":
                        file_type_filters.append(
                            "mimeType='application/vnd.google-apps.presentation'"
                        )
                    elif file_type == "folder":
                        file_type_filters.append(
                            "mimeType='application/vnd.google-apps.folder'"
                        )
                    elif file_type == "pdf":
                        file_type_filters.append("mimeType='application/pdf'")

                if file_type_filters:
                    query_parts.append(f"({' or '.join(file_type_filters)})")

            if request.owner:
                query_parts.append(f"'{request.owner}' in owners")

            if not request.include_shared:
                query_parts.append("'me' in owners")

            # Add trashed=false to exclude deleted files
            query_parts.append("trashed=false")

            full_query = (
                " and ".join(query_parts) if query_parts else "trashed=false"
            )
            logger.debug(f"Full search query: {full_query}")

            results = self.client.search_files(
                query=full_query, max_results=request.max_results
            )

            # Format results
            formatted_results = []
            for file in results:
                formatted_results.append(
                    {
                        "id": file.get("id"),
                        "name": file.get("name"),
                        "mime_type": file.get("mimeType"),
                        "owners": [
                            owner.get("emailAddress")
                            for owner in file.get("owners", [])
                        ],
                        "created_time": file.get("createdTime"),
                        "modified_time": file.get("modifiedTime"),
                        "size": file.get("size"),
                        "web_view_link": file.get("webViewLink"),
                        "permissions": [
                            {
                                "email": perm.get("emailAddress"),
                                "role": perm.get("role"),
                                "type": perm.get("type"),
                            }
                            for perm in file.get("permissions", [])
                        ],
                    }
                )

            return {
                "query": request.query,
                "total_results": len(formatted_results),
                "results": formatted_results,
            }

        except Exception as e:
            logger.error(f"Error searching documents: {str(e)}")
            raise

    def create_document(
        self, request: CreateDocumentRequest
    ) -> dict[str, Any]:
        """Create a new document in Google Drive.

        Args:
            request: CreateDocumentRequest containing document creation parameters.

        Returns:
            Dict containing the created document's details.
        """
        logger.info(
            f"Creating {request.document_type} document: {request.title}"
        )

        try:
            # Create the document
            if request.document_type == "document":
                document = self.client.create_google_doc(
                    title=request.title,
                    content=request.content or "",
                    parent_folder_id=request.parent_folder_id,
                )
            elif request.document_type == "spreadsheet":
                document = self.client.create_google_sheet(
                    title=request.title,
                    parent_folder_id=request.parent_folder_id,
                )
            elif request.document_type == "presentation":
                document = self.client.create_google_slide(
                    title=request.title,
                    parent_folder_id=request.parent_folder_id,
                )
            elif request.document_type == "folder":
                document = self.client.create_folder(
                    title=request.title,
                    parent_folder_id=request.parent_folder_id,
                )
            else:
                raise ValueError(
                    f"Unsupported document type: {request.document_type}"
                )

            # Set permissions if specified
            if request.permissions:
                for email in request.permissions:
                    self.client.share_file(
                        file_id=document["id"], email=email, role="writer"
                    )

            return {
                "message": f"{request.document_type.title()} created successfully",
                "document": {
                    "id": document["id"],
                    "name": document["name"],
                    "mime_type": document["mimeType"],
                    "web_view_link": document.get("webViewLink"),
                    "created_time": document["createdTime"],
                },
            }

        except Exception as e:
            logger.error(f"Error creating document: {str(e)}")
            raise

    def get_document(self, request: GetDocumentRequest) -> dict[str, Any]:
        """Get detailed information about a specific document.

        Args:
            request: GetDocumentRequest containing document ID and options.

        Returns:
            Dict containing the document's detailed information.
        """
        logger.info(f"Getting document: {request.document_id}")

        try:
            file_info = self.client.get_file(
                file_id=request.document_id,
                include_content=request.include_content,
            )

            result = {
                "id": file_info["id"],
                "name": file_info["name"],
                "mime_type": file_info["mimeType"],
                "owners": [
                    owner.get("emailAddress")
                    for owner in file_info.get("owners", [])
                ],
                "created_time": file_info["createdTime"],
                "modified_time": file_info["modifiedTime"],
                "size": file_info.get("size"),
                "web_view_link": file_info.get("webViewLink"),
                "permissions": [
                    {
                        "email": perm.get("emailAddress"),
                        "role": perm.get("role"),
                        "type": perm.get("type"),
                    }
                    for perm in file_info.get("permissions", [])
                ],
            }

            if request.include_content and "content" in file_info:
                result["content"] = file_info["content"]

            return result

        except Exception as e:
            logger.error(f"Error getting document: {str(e)}")
            raise

    def update_document(
        self, request: UpdateDocumentRequest
    ) -> dict[str, Any]:
        """Update an existing document in Google Drive.

        Args:
            request: UpdateDocumentRequest containing update parameters.

        Returns:
            Dict containing the update operation result.
        """
        logger.info(f"Updating document: {request.document_id}")

        try:
            update_body = {}

            if request.title:
                update_body["name"] = request.title

            # Update metadata
            if update_body:
                self.client.update_file_metadata(
                    file_id=request.document_id, update_body=update_body
                )

            # Update content if specified
            if request.content:
                self.client.update_file_content(
                    file_id=request.document_id, content=request.content
                )

            # Update permissions if specified
            if request.permissions:
                # First, get current permissions
                current_file = self.client.get_file(request.document_id)
                current_permissions = {
                    perm.get("emailAddress"): perm.get("id")
                    for perm in current_file.get("permissions", [])
                    if perm.get("type") == "user"
                }

                # Add new permissions
                for email in request.permissions:
                    if email not in current_permissions:
                        self.client.share_file(
                            file_id=request.document_id,
                            email=email,
                            role="writer",
                        )

            return {
                "message": "Document updated successfully",
                "document_id": request.document_id,
            }

        except Exception as e:
            logger.error(f"Error updating document: {str(e)}")
            raise

    def delete_document(
        self, request: DeleteDocumentRequest
    ) -> dict[str, Any]:
        """Delete a document from Google Drive.

        Args:
            request: DeleteDocumentRequest containing document ID and deletion options.

        Returns:
            Dict containing the deletion operation result.
        """
        logger.info(f"Deleting document: {request.document_id}")

        try:
            if request.permanent:
                self.client.permanently_delete_file(request.document_id)
                message = "Document permanently deleted"
            else:
                self.client.move_file_to_trash(request.document_id)
                message = "Document moved to trash"

            return {"message": message, "document_id": request.document_id}

        except Exception as e:
            logger.error(f"Error deleting document: {str(e)}")
            raise

    def copy_document(self, request: CopyDocumentRequest) -> dict[str, Any]:
        """Copy a document/file in Google Drive.

        Args:
            request: CopyDocumentRequest containing source ID, new title, and destination.

        Returns:
            Dict containing the copied document's details.
        """
        logger.info(
            "Copying document %s to %s",
            request.source_document_id,
            request.destination_folder_id or "same folder",
        )

        try:
            copied = self.client.copy_file(
                source_file_id=request.source_document_id,
                new_title=request.new_title,
                destination_folder_id=request.destination_folder_id,
            )

            if request.permissions:
                for email in request.permissions:
                    self.client.share_file(
                        file_id=copied["id"], email=email, role="writer"
                    )

            return {
                "message": "Document copied successfully",
                "document": {
                    "id": copied["id"],
                    "name": copied.get("name"),
                    "mime_type": copied.get("mimeType"),
                    "web_view_link": copied.get("webViewLink"),
                    "created_time": copied.get("createdTime"),
                },
            }

        except Exception as e:
            logger.error(f"Error copying document: {str(e)}")
            raise

    def list_folders(self, request: ListFoldersRequest) -> dict[str, Any]:
        """List folders in Google Drive.

        Args:
            request: ListFoldersRequest containing listing parameters.

        Returns:
            Dict containing the list of folders.
        """
        logger.info("Listing folders")

        try:
            query = "mimeType='application/vnd.google-apps.folder' and trashed=false"

            if request.parent_folder_id:
                query += f" and '{request.parent_folder_id}' in parents"
            else:
                query += " and 'root' in parents"

            if not request.include_shared:
                query += " and 'me' in owners"

            folders = self.client.search_files(
                query=query, max_results=request.max_results
            )

            formatted_folders = []
            for folder in folders:
                formatted_folders.append(
                    {
                        "id": folder["id"],
                        "name": folder["name"],
                        "created_time": folder["createdTime"],
                        "modified_time": folder["modifiedTime"],
                        "web_view_link": folder.get("webViewLink"),
                        "owners": [
                            owner.get("emailAddress")
                            for owner in folder.get("owners", [])
                        ],
                    }
                )

            return {
                "total_folders": len(formatted_folders),
                "folders": formatted_folders,
            }

        except Exception as e:
            logger.error(f"Error listing folders: {str(e)}")
            raise

    def list_drives(self, request: ListDrivesRequest) -> dict[str, Any]:
        """List shared drives accessible to the service account.

        Args:
            request: ListDrivesRequest containing optional name filter and max results.

        Returns:
            Dict containing the list of shared drives and metadata.
        """
        logger.info("Listing shared drives")

        try:
            drives = self.client.list_drives(
                query=request.query, max_results=request.max_results or 50
            )

            formatted_drives: list[dict[str, Any]] = []
            for drive in drives:
                formatted_drives.append(
                    {
                        "id": drive.get("id"),
                        "name": drive.get("name"),
                        "created_time": drive.get("createdTime"),
                        "capabilities": drive.get("capabilities"),
                        "restrictions": drive.get("restrictions"),
                    }
                )

            return {
                "total_drives": len(formatted_drives),
                "drives": formatted_drives,
            }

        except Exception as e:
            logger.error(f"Error listing shared drives: {str(e)}")
            raise

    def list_customer_files(
        self, request: ListCustomerFilesRequest
    ) -> dict[str, Any]:
        """List files for a given customer by navigating the customer folder hierarchy.

        The hierarchy is: CUSTOMER_ROOT -> LETTER_FOLDER -> CUSTOMER_FOLDER -> files/subfolders.

        Args:
            request: ListCustomerFilesRequest with customer name and options.

        Returns:
            Dict with the resolved customer folder id and files metadata.
        """
        logger.info("Listing customer files for %s", request.customer_name)

        root_folder_id = os.environ.get("GDRIVE_CUSTOMER_FOLDER_ID")
        if not root_folder_id:
            raise ValueError(
                "Environment variable GDRIVE_CUSTOMER_FOLDER_ID is required to list customer files"
            )

        # Resolve the letter folder (first non-space letter, uppercased)
        name = request.customer_name.strip()
        if not name:
            raise ValueError("customer_name must not be empty")
        first_letter = name[0].upper()

        # Find the letter folder under the root
        folder_mime = "application/vnd.google-apps.folder"
        letter_query = f"mimeType='{folder_mime}' and trashed=false and name='{first_letter}' and '{root_folder_id}' in parents"
        letter_folders = self.client.search_files(
            query=letter_query, max_results=1
        )
        if not letter_folders:
            raise FileNotFoundError(
                f"Letter folder '{first_letter}' not found under customer root"
            )
        letter_folder_id = letter_folders[0]["id"]

        # Find the customer folder under the letter folder
        safe_customer = name.replace("'", "\\'")
        customer_query = f"mimeType='{folder_mime}' and trashed=false and name='{safe_customer}' and '{letter_folder_id}' in parents"
        customer_folders = self.client.search_files(
            query=customer_query, max_results=1
        )
        if not customer_folders:
            raise FileNotFoundError(
                f"Customer folder '{name}' not found under letter '{first_letter}'"
            )
        customer_folder_id = customer_folders[0]["id"]

        include_owned_clause = (
            " and 'me' in owners" if not request.include_shared else ""
        )

        def list_non_folder_files(
            parent_id: str, remaining: int
        ) -> list[dict[str, Any]]:
            if remaining <= 0:
                return []
            # Exclude folders
            files_query = (
                f"mimeType!='{folder_mime}' and trashed=false and '{parent_id}' in parents"
                + include_owned_clause
            )
            return self.client.search_files(
                query=files_query, max_results=remaining
            )

        files: list[dict[str, Any]] = []

        # Always list files directly under the customer folder first
        files.extend(
            list_non_folder_files(
                customer_folder_id, request.max_results or 100
            )
        )

        # If recursive, traverse subfolders breadth-first and collect files
        if request.recursive and len(files) < (request.max_results or 100):
            # List subfolders under the customer folder and traverse
            to_visit: list[str] = [customer_folder_id]
            visited: set[str] = set()
            while to_visit and len(files) < (request.max_results or 100):
                current_parent = to_visit.pop(0)
                if current_parent in visited:
                    continue
                visited.add(current_parent)

                # Discover immediate subfolders
                subfolder_query = f"mimeType='{folder_mime}' and trashed=false and '{current_parent}' in parents"
                subfolders = self.client.search_files(
                    query=subfolder_query,
                    max_results=100,
                )
                for sub in subfolders:
                    sub_id = sub.get("id")
                    if sub_id and sub_id not in visited:
                        to_visit.append(sub_id)

                # Collect files in this folder (non-folder)
                remaining = (request.max_results or 100) - len(files)
                if remaining > 0:
                    files.extend(
                        list_non_folder_files(current_parent, remaining)
                    )

        # Format response
        formatted_files: list[dict[str, Any]] = []
        for file in files:
            formatted_files.append(
                {
                    "id": file.get("id"),
                    "name": file.get("name"),
                    "mime_type": file.get("mimeType"),
                    "owners": [
                        owner.get("emailAddress")
                        for owner in file.get("owners", [])
                    ],
                    "created_time": file.get("createdTime"),
                    "modified_time": file.get("modifiedTime"),
                    "size": file.get("size"),
                    "web_view_link": file.get("webViewLink"),
                }
            )

        return {
            "customer_name": name,
            "customer_folder_id": customer_folder_id,
            "total_files": len(formatted_files),
            "files": formatted_files,
        }
