"""Google Drive API client for MCP operations.

This module provides low-level interactions with the Google Drive API
including file operations, search, and content management.
"""

import logging
from typing import Any

from fastapi import HTTPException
from google.oauth2.credentials import Credentials
from google_admin.utils.google import get_google_credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


class GoogleDriveClient:
    """Client for interacting with Google Drive API."""

    def __init__(self):
        """Initialize the Google Drive client."""
        logger.debug("Getting Google Drive credentials")
        self.credentials: Credentials = get_google_credentials()
        self.service = build("drive", "v3", credentials=self.credentials)
        # Docs API client for content edits
        self.docs_service = build("docs", "v1", credentials=self.credentials)

    def search_files(
        self, query: str, max_results: int = 10
    ) -> list[dict[str, Any]]:
        """Search for files in Google Drive.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.

        Returns:
            List of file metadata dictionaries.
        """
        try:
            logger.debug(f"Searching files with query: {query}")

            results = (
                self.service.files()
                .list(
                    q=query,
                    pageSize=max_results,
                    corpora="allDrives",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                    fields="nextPageToken, files(id, name, mimeType, owners, createdTime, modifiedTime, size, webViewLink, permissions)",
                )
                .execute()
            )

            return results.get("files", [])

        except HttpError as e:
            logger.error(f"Google Drive API error: {e}")
            raise HTTPException(
                status_code=500, detail=f"Google Drive API error: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error searching files: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def list_drives(
        self, query: str | None = None, max_results: int = 50
    ) -> list[dict[str, Any]]:
        """List shared drives the service account can access.

        Args:
            query: Optional name filter; when provided, only drives whose name contains this value will be returned (case-insensitive).
            max_results: Maximum number of shared drives to return.

        Returns:
            List of shared drive metadata dictionaries.
        """
        try:
            logger.debug(
                "Listing shared drives%s",
                f" with query: {query}" if query else "",
            )

            kwargs: dict[str, Any] = {
                "pageSize": max_results,
                "fields": "nextPageToken, drives(id, name, createdTime, capabilities, restrictions)",
            }
            if query:
                safe = query.replace("'", "\\'")
                kwargs["q"] = f"name contains '{safe}'"

            results = self.service.drives().list(**kwargs).execute()
            return results.get("drives", [])

        except HttpError as e:
            logger.error(f"Google Drive API error: {e}")
            raise HTTPException(
                status_code=500, detail=f"Google Drive API error: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error listing shared drives: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def get_file(
        self, file_id: str, include_content: bool = False
    ) -> dict[str, Any]:
        """Get file metadata and optionally content.

        Args:
            file_id: Google Drive file ID.
            include_content: Whether to include file content.

        Returns:
            File metadata dictionary with optional content.
        """
        try:
            logger.debug(f"Getting file: {file_id}")

            # Get file metadata
            file_metadata = (
                self.service.files()
                .get(
                    fileId=file_id,
                    supportsAllDrives=True,
                    fields="id, name, mimeType, owners, createdTime, modifiedTime, size, webViewLink, permissions",
                )
                .execute()
            )

            # Get content if requested and it's a Google Doc
            if (
                include_content
                and file_metadata["mimeType"]
                == "application/vnd.google-apps.document"
            ):
                try:
                    # Export as plain text to get content
                    content = (
                        self.service.files()
                        .export_media(
                            fileId=file_id,
                            mimeType="text/plain",
                        )
                        .execute()
                    )
                    file_metadata["content"] = content.decode("utf-8")
                except Exception as e:
                    logger.warning(
                        f"Could not retrieve content for file {file_id}: {e}"
                    )
                    file_metadata["content"] = None

            return file_metadata

        except HttpError as e:
            logger.error(f"Google Drive API error: {e}")
            raise HTTPException(
                status_code=500, detail=f"Google Drive API error: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error getting file: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def create_google_doc(
        self,
        title: str,
        content: str = "",
        parent_folder_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new Google Doc.

        Args:
            title: Document title.
            content: Initial document content.
            parent_folder_id: Optional parent folder ID.

        Returns:
            Created document metadata.
        """
        try:
            logger.debug(f"Creating Google Doc: {title}")

            # Create empty document
            file_metadata = {
                "name": title,
                "mimeType": "application/vnd.google-apps.document",
            }

            if parent_folder_id:
                file_metadata["parents"] = [parent_folder_id]

            file = (
                self.service.files()
                .create(
                    body=file_metadata,
                    fields="id, name, mimeType, createdTime, webViewLink",
                )
                .execute()
            )

            # Add content if provided
            if content:
                self._update_doc_content(file["id"], content)

            return file

        except HttpError as e:
            logger.error(f"Google Drive API error: {e}")
            raise HTTPException(
                status_code=500, detail=f"Google Drive API error: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error creating Google Doc: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def create_google_sheet(
        self, title: str, parent_folder_id: str | None = None
    ) -> dict[str, Any]:
        """Create a new Google Sheet.

        Args:
            title: Sheet title.
            parent_folder_id: Optional parent folder ID.

        Returns:
            Created sheet metadata.
        """
        try:
            logger.debug(f"Creating Google Sheet: {title}")

            file_metadata = {
                "name": title,
                "mimeType": "application/vnd.google-apps.spreadsheet",
            }

            if parent_folder_id:
                file_metadata["parents"] = [parent_folder_id]

            file = (
                self.service.files()
                .create(
                    body=file_metadata,
                    fields="id, name, mimeType, createdTime, webViewLink",
                )
                .execute()
            )

            return file

        except HttpError as e:
            logger.error(f"Google Drive API error: {e}")
            raise HTTPException(
                status_code=500, detail=f"Google Drive API error: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error creating Google Sheet: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def create_google_slide(
        self, title: str, parent_folder_id: str | None = None
    ) -> dict[str, Any]:
        """Create a new Google Slide presentation.

        Args:
            title: Presentation title.
            parent_folder_id: Optional parent folder ID.

        Returns:
            Created presentation metadata.
        """
        try:
            logger.debug(f"Creating Google Slide: {title}")

            file_metadata = {
                "name": title,
                "mimeType": "application/vnd.google-apps.presentation",
            }

            if parent_folder_id:
                file_metadata["parents"] = [parent_folder_id]

            file = (
                self.service.files()
                .create(
                    body=file_metadata,
                    fields="id, name, mimeType, createdTime, webViewLink",
                )
                .execute()
            )

            return file

        except HttpError as e:
            logger.error(f"Google Drive API error: {e}")
            raise HTTPException(
                status_code=500, detail=f"Google Drive API error: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error creating Google Slide: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def create_folder(
        self, title: str, parent_folder_id: str | None = None
    ) -> dict[str, Any]:
        """Create a new folder.

        Args:
            title: Folder title.
            parent_folder_id: Optional parent folder ID.

        Returns:
            Created folder metadata.
        """
        try:
            logger.debug(f"Creating folder: {title}")

            file_metadata = {
                "name": title,
                "mimeType": "application/vnd.google-apps.folder",
            }

            if parent_folder_id:
                file_metadata["parents"] = [parent_folder_id]

            file = (
                self.service.files()
                .create(
                    body=file_metadata,
                    fields="id, name, mimeType, createdTime, webViewLink",
                )
                .execute()
            )

            return file

        except HttpError as e:
            logger.error(f"Google Drive API error: {e}")
            raise HTTPException(
                status_code=500, detail=f"Google Drive API error: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error creating folder: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def update_file_metadata(
        self, file_id: str, update_body: dict[str, Any]
    ) -> dict[str, Any]:
        """Update file metadata.

        Args:
            file_id: Google Drive file ID.
            update_body: Metadata fields to update.

        Returns:
            Updated file metadata.
        """
        try:
            logger.debug(f"Updating file metadata: {file_id}")

            file = (
                self.service.files()
                .update(
                    fileId=file_id,
                    body=update_body,
                    fields="id, name, mimeType, modifiedTime",
                )
                .execute()
            )

            return file

        except HttpError as e:
            logger.error(f"Google Drive API error: {e}")
            raise HTTPException(
                status_code=500, detail=f"Google Drive API error: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error updating file metadata: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def update_file_content(self, file_id: str, content: str) -> None:
        """Update file content (for Google Docs).

        Args:
            file_id: Google Drive file ID.
            content: New content to set.
        """
        try:
            logger.debug(f"Updating file content: {file_id}")
            # Use Google Docs API to replace entire document body with provided text
            # 1) Fetch current document to determine end index
            document = (
                self.docs_service.documents().get(documentId=file_id).execute()
            )
            body = document.get("body", {})
            content_elements = body.get("content", [])
            # The last content element's endIndex marks the end of the document
            end_index = (
                content_elements[-1]["endIndex"] if content_elements else 1
            )

            requests: list[dict[str, Any]] = []
            if end_index > 1:
                requests.append(
                    {
                        "deleteContentRange": {
                            "range": {
                                "startIndex": 1,
                                "endIndex": end_index - 1,
                            }
                        }
                    }
                )
            if content:
                requests.append(
                    {
                        "insertText": {
                            "location": {"index": 1},
                            "text": content,
                        }
                    }
                )

            if not requests:
                return

            (
                self.docs_service.documents()
                .batchUpdate(documentId=file_id, body={"requests": requests})
                .execute()
            )

        except Exception as e:
            logger.error(f"Error updating file content: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def share_file(
        self, file_id: str, email: str, role: str = "writer"
    ) -> dict[str, Any]:
        """Share a file with a specific user.

        Args:
            file_id: Google Drive file ID.
            email: Email address to share with.
            role: Permission role (reader, writer, owner).

        Returns:
            Permission metadata.
        """
        try:
            logger.debug(f"Sharing file {file_id} with {email} as {role}")

            permission = {"type": "user", "role": role, "emailAddress": email}

            result = (
                self.service.permissions()
                .create(
                    fileId=file_id,
                    body=permission,
                    fields="id, emailAddress, role",
                )
                .execute()
            )

            return result

        except HttpError as e:
            logger.error(f"Google Drive API error: {e}")
            raise HTTPException(
                status_code=500, detail=f"Google Drive API error: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error sharing file: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def move_file_to_trash(self, file_id: str) -> None:
        """Move a file to trash.

        Args:
            file_id: Google Drive file ID.
        """
        try:
            logger.debug(f"Moving file to trash: {file_id}")

            self.service.files().delete(fileId=file_id).execute()

        except HttpError as e:
            logger.error(f"Google Drive API error: {e}")
            raise HTTPException(
                status_code=500, detail=f"Google Drive API error: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error moving file to trash: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def permanently_delete_file(self, file_id: str) -> None:
        """Permanently delete a file.

        Args:
            file_id: Google Drive file ID.
        """
        try:
            logger.debug(f"Permanently deleting file: {file_id}")

            self.service.files().delete(fileId=file_id).execute()

        except HttpError as e:
            logger.error(f"Google Drive API error: {e}")
            raise HTTPException(
                status_code=500, detail=f"Google Drive API error: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error permanently deleting file: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def copy_file(
        self,
        source_file_id: str,
        new_title: str | None = None,
        destination_folder_id: str | None = None,
    ) -> dict[str, Any]:
        """Copy a file in Google Drive.

        Args:
            source_file_id: The ID of the file to copy.
            new_title: Optional new title for the copied file.
            destination_folder_id: Optional destination folder ID for the copied file.

        Returns:
            Metadata for the newly copied file.
        """
        try:
            logger.debug(
                "Copying file %s to folder %s with title %s",
                source_file_id,
                destination_folder_id,
                new_title,
            )

            body: dict[str, Any] = {}
            if new_title:
                body["name"] = new_title
            if destination_folder_id:
                body["parents"] = [destination_folder_id]

            copied = (
                self.service.files()
                .copy(
                    fileId=source_file_id,
                    body=body,
                    supportsAllDrives=True,
                    fields="id, name, mimeType, owners, createdTime, modifiedTime, size, webViewLink",
                )
                .execute()
            )

            return copied

        except HttpError as e:
            logger.error(f"Google Drive API error: {e}")
            raise HTTPException(
                status_code=500, detail=f"Google Drive API error: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error copying file: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    def _update_doc_content(self, file_id: str, content: str) -> None:
        """Update Google Doc content using the Docs API.

        Args:
            file_id: Google Drive file ID.
            content: New content to set.
        """
        try:
            self.update_file_content(file_id=file_id, content=content)

        except Exception as e:
            logger.error(f"Error updating doc content: {str(e)}")
            raise
