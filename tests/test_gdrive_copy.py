"""Tests for Google Drive copy document functionality."""

from unittest.mock import Mock, patch

import pytest

from google_mcp.gdrive_mcp.drive_client import GoogleDriveClient
from google_mcp.gdrive_mcp.models import CopyDocumentRequest
from google_mcp.gdrive_mcp.service import GoogleDriveService


class TestCopyDocumentModel:
    """Tests for CopyDocumentRequest model."""

    def test_minimal(self) -> None:
        req = CopyDocumentRequest(source_document_id="abc123")
        assert req.source_document_id == "abc123"
        assert req.new_title is None
        assert req.destination_folder_id is None
        assert req.permissions is None

    def test_full(self) -> None:
        req = CopyDocumentRequest(
            source_document_id="abc123",
            new_title="Copy",
            destination_folder_id="folder1",
            permissions=["user@example.com"],
        )
        assert req.new_title == "Copy"
        assert req.destination_folder_id == "folder1"
        assert req.permissions == ["user@example.com"]


class TestCopyDocumentService:
    """Tests for GoogleDriveService.copy_document."""

    @pytest.fixture
    def mock_client(self) -> Mock:
        return Mock(spec=GoogleDriveClient)

    @pytest.fixture
    def service(self, mock_client: Mock) -> GoogleDriveService:
        with patch(
            "google_mcp.gdrive_mcp.service.GoogleDriveClient",
            return_value=mock_client,
        ):
            return GoogleDriveService()

    def test_copy_without_permissions(
        self, service: GoogleDriveService, mock_client: Mock
    ) -> None:
        mock_client.copy_file.return_value = {
            "id": "copied1",
            "name": "Copied",
            "mimeType": "application/vnd.google-apps.document",
            "createdTime": "2024-01-01T00:00:00Z",
            "webViewLink": "https://docs.google.com/copied1",
        }

        req = CopyDocumentRequest(
            source_document_id="src1", new_title="Copied"
        )
        result = service.copy_document(req)

        assert result["message"] == "Document copied successfully"
        assert result["document"]["id"] == "copied1"
        mock_client.copy_file.assert_called_once_with(
            source_file_id="src1",
            new_title="Copied",
            destination_folder_id=None,
        )
        mock_client.share_file.assert_not_called()

    def test_copy_with_permissions(
        self, service: GoogleDriveService, mock_client: Mock
    ) -> None:
        mock_client.copy_file.return_value = {
            "id": "copied2",
            "name": "Copied",
        }

        req = CopyDocumentRequest(
            source_document_id="src2",
            destination_folder_id="folder1",
            permissions=["a@example.com", "b@example.com"],
        )
        service.copy_document(req)

        mock_client.copy_file.assert_called_once_with(
            source_file_id="src2",
            new_title=None,
            destination_folder_id="folder1",
        )
        assert mock_client.share_file.call_count == 2


class TestCopyDocumentClient:
    """Tests for GoogleDriveClient.copy_file."""

    @patch("google_mcp.gdrive_mcp.drive_client.build")
    @patch("google_mcp.gdrive_mcp.drive_client.get_google_credentials")
    def test_copy_file_api_chain(
        self, mock_get_creds: Mock, mock_build: Mock
    ) -> None:
        mock_get_creds.return_value = Mock()
        mock_service = Mock()
        mock_build.return_value = mock_service

        mock_files = Mock()
        mock_copy = Mock()
        mock_copy.execute.return_value = {"id": "new", "name": "New Name"}
        mock_service.files.return_value = mock_files
        mock_files.copy.return_value = mock_copy

        client = GoogleDriveClient()
        result = client.copy_file(
            "src", new_title="New Name", destination_folder_id="folderX"
        )

        assert result["id"] == "new"
        mock_service.files.assert_called_once()
        mock_files.copy.assert_called_once()
        kwargs = mock_files.copy.call_args.kwargs
        assert kwargs["fileId"] == "src"
        assert kwargs["body"] == {"name": "New Name", "parents": ["folderX"]}
        assert kwargs["supportsAllDrives"] is True
        assert "fields" in kwargs
