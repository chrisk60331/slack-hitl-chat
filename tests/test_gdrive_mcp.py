from typing import Any

from google_mcp.gdrive_mcp.models import ListCustomerFilesRequest
from google_mcp.gdrive_mcp.service import GoogleDriveService


def test_list_customer_files_model_defaults() -> None:
    req = ListCustomerFilesRequest(customer_name="Acme Corp")
    assert req.customer_name == "Acme Corp"
    assert req.recursive is False
    assert req.max_results == 100
    assert req.include_shared is True


def test_service_builds_queries(monkeypatch: Any) -> None:
    # Prepare a fake client
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        def search_files(self, query: str, max_results: int = 10):
            self.calls.append((query, max_results))
            # Simulate letter folder found first, then customer folder, then files
            if (
                "in parents" in query
                and "mimeType='application/vnd.google-apps.folder'" in query
            ):
                if "name='A'" in query:
                    return [{"id": "letterA"}]
                if "name='Acme Corp'" in query:
                    return [{"id": "custAcme"}]
                # subfolders listing returns none
                return []
            # files query (non-folder)
            if "mimeType!='application/vnd.google-apps.folder'" in query:
                return [
                    {
                        "id": "f1",
                        "name": "Doc1",
                        "mimeType": "application/vnd.google-apps.document",
                        "owners": [{"emailAddress": "owner@example.com"}],
                        "createdTime": "2024-01-01T00:00:00Z",
                        "modifiedTime": "2024-01-02T00:00:00Z",
                        "size": None,
                        "webViewLink": "https://drive.google.com/",
                    }
                ]
            return []

    svc = GoogleDriveService()
    # Monkeypatch the underlying client
    svc.client = FakeClient()
    # Set env var for root
    monkeypatch.setenv("GDRIVE_CUSTOMER_FOLDER_ID", "root123")

    req = ListCustomerFilesRequest(customer_name="Acme Corp")
    out = svc.list_customer_files(req)

    assert out["customer_folder_id"] == "custAcme"
    assert out["total_files"] == 1
    assert out["files"][0]["name"] == "Doc1"


"""Unit tests for Google Drive MCP functionality."""

from unittest.mock import Mock, patch

import pytest

from google_mcp.gdrive_mcp.drive_client import GoogleDriveClient
from google_mcp.gdrive_mcp.models import (
    CreateDocumentRequest,
    DeleteDocumentRequest,
    GetDocumentRequest,
    ListDrivesRequest,
    ListFoldersRequest,
    SearchDocumentsRequest,
    UpdateDocumentRequest,
)


class TestSearchDocumentsRequest:
    """Test SearchDocumentsRequest model."""

    def test_valid_request(self):
        """Test valid search request creation."""
        request = SearchDocumentsRequest(
            query="test document",
            file_types=["document", "spreadsheet"],
            max_results=20,
            include_shared=False,
        )

        assert request.query == "test document"
        assert request.file_types == ["document", "spreadsheet"]
        assert request.max_results == 20
        assert request.include_shared is False

    def test_minimal_request(self):
        """Test minimal search request with only required fields."""
        request = SearchDocumentsRequest(query="test")

        assert request.query == "test"
        assert request.file_types is None
        assert request.max_results == 10
        assert request.include_shared is True

    def test_file_types_validation(self):
        """Test file types validation."""
        request = SearchDocumentsRequest(
            query="test", file_types=["document", "invalid_type"]
        )

        # Should accept valid types and ignore invalid ones
        assert "document" in request.file_types


class TestCreateDocumentRequest:
    """Test CreateDocumentRequest model."""

    def test_valid_request(self):
        """Test valid create document request."""
        request = CreateDocumentRequest(
            title="Test Document",
            document_type="document",
            content="Initial content",
            permissions=["user@example.com"],
        )

        assert request.title == "Test Document"
        assert request.document_type == "document"
        assert request.content == "Initial content"
        assert request.permissions == ["user@example.com"]

    def test_minimal_request(self):
        """Test minimal create document request."""
        request = CreateDocumentRequest(title="Test", document_type="folder")

        assert request.title == "Test"
        assert request.document_type == "folder"
        assert request.content is None
        assert request.permissions is None


class TestGetDocumentRequest:
    """Test GetDocumentRequest model."""

    def test_valid_request(self):
        """Test valid get document request."""
        request = GetDocumentRequest(document_id="12345", include_content=True)

        assert request.document_id == "12345"
        assert request.include_content is True

    def test_default_values(self):
        """Test default values for get document request."""
        request = GetDocumentRequest(document_id="12345")

        assert request.document_id == "12345"
        assert request.include_content is False


class TestUpdateDocumentRequest:
    """Test UpdateDocumentRequest model."""

    def test_valid_request(self):
        """Test valid update document request."""
        request = UpdateDocumentRequest(
            document_id="12345",
            title="Updated Title",
            content="Updated content",
        )

        assert request.document_id == "12345"
        assert request.title == "Updated Title"
        assert request.content == "Updated content"

    def test_partial_update(self):
        """Test partial update request."""
        request = UpdateDocumentRequest(document_id="12345")

        assert request.document_id == "12345"
        assert request.title is None
        assert request.content is None


class TestDeleteDocumentRequest:
    """Test DeleteDocumentRequest model."""

    def test_valid_request(self):
        """Test valid delete document request."""
        request = DeleteDocumentRequest(document_id="12345", permanent=True)

        assert request.document_id == "12345"
        assert request.permanent is True

    def test_default_values(self):
        """Test default values for delete document request."""
        request = DeleteDocumentRequest(document_id="12345")

        assert request.document_id == "12345"
        assert request.permanent is False


class TestListFoldersRequest:
    """Test ListFoldersRequest model."""

    def test_valid_request(self):
        """Test valid list folders request."""
        request = ListFoldersRequest(
            parent_folder_id="parent123", max_results=100, include_shared=False
        )

        assert request.parent_folder_id == "parent123"
        assert request.max_results == 100
        assert request.include_shared is False

    def test_default_values(self):
        """Test default values for list folders request."""
        request = ListFoldersRequest()

        assert request.parent_folder_id is None
        assert request.max_results == 50
        assert request.include_shared is True


class TestGoogleDriveService:
    """Test GoogleDriveService class."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock Google Drive client."""
        return Mock(spec=GoogleDriveClient)

    @pytest.fixture
    def service(self, mock_client):
        """Create a service instance with mocked client."""
        with patch(
            "google_mcp.gdrive_mcp.service.GoogleDriveClient",
            return_value=mock_client,
        ):
            return GoogleDriveService()

    def test_search_documents(self, service, mock_client):
        """Test document search functionality."""
        # Mock search results
        mock_results = [
            {
                "id": "doc1",
                "name": "Test Document",
                "mimeType": "application/vnd.google-apps.document",
                "owners": [{"emailAddress": "owner@example.com"}],
                "createdTime": "2024-01-01T00:00:00Z",
                "modifiedTime": "2024-01-01T00:00:00Z",
                "size": "1024",
                "webViewLink": "https://docs.google.com/doc1",
                "permissions": [],
            }
        ]
        mock_client.search_files.return_value = mock_results

        request = SearchDocumentsRequest(
            query="test", file_types=["document"], max_results=5
        )

        result = service.search_documents(request)

        assert result["query"] == "test"
        assert result["total_results"] == 1
        assert len(result["results"]) == 1
        assert result["results"][0]["name"] == "Test Document"

        # Verify client was called with correct query
        mock_client.search_files.assert_called_once()
        call_args = mock_client.search_files.call_args
        built_query = call_args[1]["query"]
        assert "trashed=false" in built_query
        assert (
            "name contains 'test'" in built_query
            or "fullText contains 'test'" in built_query
        )

    def test_create_document(self, service, mock_client):
        """Test document creation functionality."""
        mock_doc = {
            "id": "new_doc",
            "name": "New Document",
            "mimeType": "application/vnd.google-apps.document",
            "createdTime": "2024-01-01T00:00:00Z",
            "webViewLink": "https://docs.google.com/new_doc",
        }
        mock_client.create_google_doc.return_value = mock_doc

        request = CreateDocumentRequest(
            title="New Document",
            document_type="document",
            content="Initial content",
        )

        result = service.create_document(request)

        assert result["message"] == "Document created successfully"
        assert result["document"]["id"] == "new_doc"
        assert result["document"]["name"] == "New Document"

        mock_client.create_google_doc.assert_called_once_with(
            title="New Document",
            content="Initial content",
            parent_folder_id=None,
        )

    def test_create_spreadsheet(self, service, mock_client):
        """Test spreadsheet creation functionality."""
        mock_sheet = {
            "id": "new_sheet",
            "name": "New Sheet",
            "mimeType": "application/vnd.google-apps.spreadsheet",
            "createdTime": "2024-01-01T00:00:00Z",
        }
        mock_client.create_google_sheet.return_value = mock_sheet

        request = CreateDocumentRequest(
            title="New Sheet", document_type="spreadsheet"
        )

        result = service.create_document(request)

        assert result["message"] == "Spreadsheet created successfully"
        assert result["document"]["id"] == "new_sheet"

        mock_client.create_google_sheet.assert_called_once_with(
            title="New Sheet", parent_folder_id=None
        )

    def test_create_folder(self, service, mock_client):
        """Test folder creation functionality."""
        mock_folder = {
            "id": "new_folder",
            "name": "New Folder",
            "mimeType": "application/vnd.google-apps.folder",
            "createdTime": "2024-01-01T00:00:00Z",
        }
        mock_client.create_folder.return_value = mock_folder

        request = CreateDocumentRequest(
            title="New Folder", document_type="folder"
        )

        result = service.create_document(request)

        assert result["message"] == "Folder created successfully"
        assert result["document"]["id"] == "new_folder"

        mock_client.create_folder.assert_called_once_with(
            title="New Folder", parent_folder_id=None
        )

    def test_get_document(self, service, mock_client):
        """Test document retrieval functionality."""
        mock_file = {
            "id": "doc1",
            "name": "Test Document",
            "mimeType": "application/vnd.google-apps.document",
            "owners": [{"emailAddress": "owner@example.com"}],
            "createdTime": "2024-01-01T00:00:00Z",
            "modifiedTime": "2024-01-01T00:00:00Z",
            "size": "1024",
            "webViewLink": "https://docs.google.com/doc1",
            "permissions": [],
        }
        mock_client.get_file.return_value = mock_file

        request = GetDocumentRequest(document_id="doc1", include_content=False)

        result = service.get_document(request)

        assert result["id"] == "doc1"
        assert result["name"] == "Test Document"
        assert "content" not in result

        mock_client.get_file.assert_called_once_with(
            file_id="doc1", include_content=False
        )

    def test_update_document(self, service, mock_client):
        """Test document update functionality."""
        mock_client.update_file_metadata.return_value = {
            "id": "doc1",
            "name": "Updated",
        }

        request = UpdateDocumentRequest(
            document_id="doc1", title="Updated Title"
        )

        result = service.update_document(request)

        assert result["message"] == "Document updated successfully"
        assert result["document_id"] == "doc1"

        mock_client.update_file_metadata.assert_called_once_with(
            file_id="doc1", update_body={"name": "Updated Title"}
        )

    def test_delete_document_trash(self, service, mock_client):
        """Test document deletion (move to trash)."""
        request = DeleteDocumentRequest(document_id="doc1", permanent=False)

        result = service.delete_document(request)

        assert result["message"] == "Document moved to trash"
        assert result["document_id"] == "doc1"

        mock_client.move_file_to_trash.assert_called_once_with("doc1")

    def test_delete_document_permanent(self, service, mock_client):
        """Test permanent document deletion."""
        request = DeleteDocumentRequest(document_id="doc1", permanent=True)

        result = service.delete_document(request)

        assert result["message"] == "Document permanently deleted"
        assert result["document_id"] == "doc1"

        mock_client.permanently_delete_file.assert_called_once_with("doc1")

    def test_list_folders(self, service, mock_client):
        """Test folder listing functionality."""
        mock_folders = [
            {
                "id": "folder1",
                "name": "Test Folder",
                "mimeType": "application/vnd.google-apps.folder",
                "createdTime": "2024-01-01T00:00:00Z",
                "modifiedTime": "2024-01-01T00:00:00Z",
                "webViewLink": "https://drive.google.com/folder1",
                "owners": [{"emailAddress": "owner@example.com"}],
            }
        ]
        mock_client.search_files.return_value = mock_folders

        request = ListFoldersRequest(
            parent_folder_id="parent123", max_results=25
        )

        result = service.list_folders(request)

        assert result["total_folders"] == 1
        assert len(result["folders"]) == 1
        assert result["folders"][0]["name"] == "Test Folder"

        # Verify search query includes folder type and parent filter
        mock_client.search_files.assert_called_once()
        call_args = mock_client.search_files.call_args
        assert (
            "mimeType='application/vnd.google-apps.folder'"
            in call_args[1]["query"]
        )
        assert "parent123" in call_args[1]["query"]

    def test_search_with_file_type_filters(self, service, mock_client):
        """Test search with file type filtering."""
        mock_client.search_files.return_value = []

        request = SearchDocumentsRequest(
            query="test", file_types=["document", "spreadsheet"]
        )

        service.search_documents(request)

        # Verify file type filters are applied
        mock_client.search_files.assert_called_once()
        call_args = mock_client.search_files.call_args
        query = call_args[1]["query"]
        assert "mimeType='application/vnd.google-apps.document'" in query
        assert "mimeType='application/vnd.google-apps.spreadsheet'" in query

    def test_search_escapes_single_quotes(self, service, mock_client):
        """Ensure single quotes in query are escaped for Drive q syntax."""
        mock_client.search_files.return_value = []

        request = SearchDocumentsRequest(
            query="client's SOW",
        )

        service.search_documents(request)

        mock_client.search_files.assert_called_once()
        built_query = mock_client.search_files.call_args[1]["query"]
        assert "client\\'s SOW" in built_query

    def test_search_with_owner_filter(self, service, mock_client):
        """Test search with owner filtering."""
        mock_client.search_files.return_value = []

        request = SearchDocumentsRequest(
            query="test", owner="owner@example.com"
        )

        service.search_documents(request)

        # Verify owner filter is applied
        mock_client.search_files.assert_called_once()
        call_args = mock_client.search_files.call_args
        query = call_args[1]["query"]
        assert "'owner@example.com' in owners" in query

    def test_search_exclude_shared(self, service, mock_client):
        """Test search excluding shared documents."""
        mock_client.search_files.return_value = []

        request = SearchDocumentsRequest(query="test", include_shared=False)

        service.search_documents(request)

        # Verify shared documents are excluded
        mock_client.search_files.assert_called_once()
        call_args = mock_client.search_files.call_args
        query = call_args[1]["query"]
        assert "'me' in owners" in query


class TestGoogleDriveClient:
    """Test GoogleDriveClient class."""

    @pytest.fixture
    def mock_credentials(self):
        """Create mock Google credentials."""
        return Mock()

    @pytest.fixture
    def mock_service(self):
        """Create mock Google Drive service."""
        return Mock()

    @patch("google_mcp.gdrive_mcp.drive_client.build")
    @patch("google_mcp.gdrive_mcp.drive_client.get_google_credentials")
    def test_list_drives(
        self, mock_get_creds, mock_build, mock_credentials, mock_service
    ):
        """Test listing shared drives."""
        mock_get_creds.return_value = mock_credentials
        mock_build.return_value = mock_service

        # Mock the drives().list() chain
        mock_drives = Mock()
        mock_list = Mock()
        mock_list.execute.return_value = {
            "drives": [
                {
                    "id": "drive1",
                    "name": "Team Drive",
                    "createdTime": "2024-01-01T00:00:00Z",
                    "capabilities": {"canShare": True},
                    "restrictions": {"copyRequiresWriterPermission": False},
                }
            ]
        }
        mock_service.drives.return_value = mock_drives
        mock_drives.list.return_value = mock_list

        client = GoogleDriveClient()
        result = client.list_drives(query="Team", max_results=10)

        assert len(result) == 1
        assert result[0]["id"] == "drive1"

        mock_service.drives.assert_called_once()
        mock_drives.list.assert_called_once()
        kwargs = mock_drives.list.call_args.kwargs
        assert kwargs["pageSize"] == 10
        assert "name contains 'Team'" in kwargs.get("q", "")


class TestGoogleDriveServiceListDrives:
    @pytest.fixture
    def mock_client(self):
        return Mock()

    @pytest.fixture
    def service(self, mock_client):
        with patch(
            "google_mcp.gdrive_mcp.service.GoogleDriveClient",
            return_value=mock_client,
        ):
            return GoogleDriveService()

    def test_list_drives_service(self, service, mock_client):
        mock_client.list_drives.return_value = [
            {
                "id": "drive1",
                "name": "Team Drive",
                "createdTime": "2024-01-01T00:00:00Z",
                "capabilities": {"canShare": True},
                "restrictions": {"copyRequiresWriterPermission": False},
            }
        ]

        request = ListDrivesRequest(query="Team", max_results=5)
        result = service.list_drives(request)

        assert result["total_drives"] == 1
        assert result["drives"][0]["name"] == "Team Drive"
        mock_client.list_drives.assert_called_once_with(
            query="Team", max_results=5
        )

    def test_client_initialization(
        self, mock_get_creds, mock_build, mock_credentials, mock_service
    ):
        """Test client initialization for Drive and Docs services."""
        mock_get_creds.return_value = mock_credentials
        mock_build.return_value = mock_service

        client = GoogleDriveClient()

        assert client.credentials == mock_credentials
        assert client.service is not None
        assert client.docs_service is not None
        # Verify we build Drive v3 and Docs v1 services
        calls = mock_build.call_args_list
        assert any(
            args[0] == ("drive", "v3")
            and (args[1].get("credentials") == mock_credentials)
            for args in list(calls)
        )
        assert any(
            args[0] == ("docs", "v1")
            and (args[1].get("credentials") == mock_credentials)
            for args in list(calls)
        )

    @patch("google_mcp.gdrive_mcp.drive_client.build")
    @patch("google_mcp.gdrive_mcp.drive_client.get_google_credentials")
    def test_search_files(
        self, mock_get_creds, mock_build, mock_credentials, mock_service
    ):
        """Test file search functionality."""
        mock_get_creds.return_value = mock_credentials
        mock_build.return_value = mock_service

        # Mock the files().list() chain
        mock_files = Mock()
        mock_list = Mock()
        mock_execute = Mock()

        mock_service.files.return_value = mock_files
        mock_files.list.return_value = mock_list
        mock_list.execute.return_value = mock_execute
        mock_execute.get.return_value = [{"id": "file1", "name": "test"}]

        client = GoogleDriveClient()
        result = client.search_files("test query", 5)

        assert len(result) == 1
        assert result[0]["id"] == "file1"

        # Verify the API call chain
        mock_service.files.assert_called_once()
        mock_files.list.assert_called_once_with(
            q="test query",
            pageSize=5,
            corpora="allDrives",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            fields="nextPageToken, files(id, name, mimeType, owners, createdTime, modifiedTime, size, webViewLink, permissions)",
        )

    @patch("google_mcp.gdrive_mcp.drive_client.build")
    @patch("google_mcp.gdrive_mcp.drive_client.get_google_credentials")
    def test_create_google_doc(
        self, mock_get_creds, mock_build, mock_credentials, mock_service
    ):
        """Test Google Doc creation."""
        mock_get_creds.return_value = mock_credentials
        mock_build.return_value = mock_service

        # Mock the files().create() chain
        mock_files = Mock()
        mock_create = Mock()
        Mock()

        mock_service.files.return_value = mock_files
        mock_files.create.return_value = mock_create
        mock_create.execute.return_value = {
            "id": "doc1",
            "name": "Test Doc",
            "mimeType": "application/vnd.google-apps.document",
        }

        client = GoogleDriveClient()
        result = client.create_google_doc("Test Doc", "Initial content")

        assert result["id"] == "doc1"
        assert result["name"] == "Test Doc"

        # Verify the API call
        mock_files.create.assert_called_once_with(
            body={
                "name": "Test Doc",
                "mimeType": "application/vnd.google-apps.document",
            },
            fields="id, name, mimeType, createdTime, webViewLink",
        )

    @patch("google_mcp.gdrive_mcp.drive_client.build")
    @patch("google_mcp.gdrive_mcp.drive_client.get_google_credentials")
    def test_get_file_with_content(
        self, mock_get_creds, mock_build, mock_credentials, mock_service
    ):
        """Test file retrieval with content."""
        mock_get_creds.return_value = mock_credentials
        mock_build.return_value = mock_service

        # Mock the files().get() chain
        mock_files = Mock()
        mock_get = Mock()
        Mock()

        mock_service.files.return_value = mock_files
        mock_files.get.return_value = mock_get
        mock_get.execute.return_value = {
            "id": "doc1",
            "name": "Test Doc",
            "mimeType": "application/vnd.google-apps.document",
        }

        # Mock export_media for content
        mock_export = Mock()
        mock_export.execute.return_value = b"Document content"
        mock_files.export_media.return_value = mock_export

        client = GoogleDriveClient()
        result = client.get_file("doc1", include_content=True)

        assert result["id"] == "doc1"
        assert result["content"] == "Document content"

        # Verify both API calls
        mock_files.get.assert_called_once()
        mock_files.export_media.assert_called_once_with(
            fileId="doc1", mimeType="text/plain", supportsAllDrives=True
        )

    @patch("google_mcp.gdrive_mcp.drive_client.build")
    @patch("google_mcp.gdrive_mcp.drive_client.get_google_credentials")
    def test_share_file(
        self, mock_get_creds, mock_build, mock_credentials, mock_service
    ):
        """Test file sharing functionality."""
        mock_get_creds.return_value = mock_credentials
        mock_build.return_value = mock_service

        # Mock the permissions().create() chain
        mock_permissions = Mock()
        mock_create = Mock()
        Mock()

        mock_service.permissions.return_value = mock_permissions
        mock_permissions.create.return_value = mock_create
        mock_create.execute.return_value = {
            "id": "perm1",
            "emailAddress": "user@example.com",
            "role": "writer",
        }

        client = GoogleDriveClient()
        result = client.share_file("file1", "user@example.com", "writer")

        assert result["id"] == "perm1"
        assert result["emailAddress"] == "user@example.com"
        assert result["role"] == "writer"

        # Verify the API call
        mock_permissions.create.assert_called_once_with(
            fileId="file1",
            body={
                "type": "user",
                "role": "writer",
                "emailAddress": "user@example.com",
            },
            fields="id, emailAddress, role",
        )

    @patch("google_mcp.gdrive_mcp.drive_client.build")
    @patch("google_mcp.gdrive_mcp.drive_client.get_google_credentials")
    def test_update_file_content_uses_docs_api(
        self, mock_get_creds: Mock, mock_build: Mock
    ) -> None:
        mock_get_creds.return_value = Mock()
        # mock_build will be called twice: once for drive v3, once for docs v1
        mock_drive_service = Mock()
        mock_docs_service = Mock()
        mock_build.side_effect = [mock_drive_service, mock_docs_service]

        # Docs.get returns a body with content having endIndex
        mock_docs_documents = Mock()
        mock_docs_service.documents.return_value = mock_docs_documents
        mock_docs_get = Mock()
        mock_docs_get.execute.return_value = {
            "body": {"content": [{"endIndex": 10}]}
        }
        mock_docs_documents.get.return_value = mock_docs_get
        mock_docs_batch = Mock()
        mock_docs_batch.execute.return_value = {}
        mock_docs_documents.batchUpdate.return_value = mock_docs_batch

        client = GoogleDriveClient()
        client.update_file_content("doc123", "Hello World")

        # Ensure Docs API batchUpdate called with delete + insert
        mock_docs_documents.batchUpdate.assert_called_once()
        kwargs = mock_docs_documents.batchUpdate.call_args.kwargs
        assert kwargs["documentId"] == "doc123"
        requests = kwargs["body"]["requests"]
        assert any("deleteContentRange" in r for r in requests)
        assert any("insertText" in r for r in requests)


if __name__ == "__main__":
    pytest.main([__file__])
