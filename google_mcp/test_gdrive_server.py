#!/usr/bin/env python3
"""Test script for Google Drive MCP Server.

This script tests that the Google Drive MCP server can start and run properly.
"""

import os
import sys

# Add the google_mcp directory to the path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)


def test_imports():
    """Test that all required modules can be imported."""
    try:
        from gdrive_mcp.models import (
            CreateDocumentRequest,
            DeleteDocumentRequest,
            GetDocumentRequest,
            ListFoldersRequest,
            SearchDocumentsRequest,
            UpdateDocumentRequest,
        )

        print("✓ All models imported successfully")

        from gdrive_mcp.service import GoogleDriveService

        print("✓ Service imported successfully")

        from gdrive_mcp.drive_client import GoogleDriveClient

        print("✓ Drive client imported successfully")

        from gdrive_mcp.mcp_server import mcp

        print("✓ MCP server imported successfully")

        return True

    except ImportError as e:
        print(f"✗ Import error: {e}")
        return False
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return False


def test_model_creation():
    """Test that models can be created with valid data."""
    try:
        # Test search request
        search_req = SearchDocumentsRequest(
            query="test document", file_types=["document"], max_results=5
        )
        assert search_req.query == "test document"
        print("✓ SearchDocumentsRequest created successfully")

        # Test create request
        create_req = CreateDocumentRequest(
            title="Test Doc", document_type="document"
        )
        assert create_req.title == "Test Doc"
        print("✓ CreateDocumentRequest created successfully")

        # Test get request
        get_req = GetDocumentRequest(document_id="12345")
        assert get_req.document_id == "12345"
        print("✓ GetDocumentRequest created successfully")

        return True

    except Exception as e:
        print(f"✗ Model creation error: {e}")
        return False


def test_mcp_server_tools():
    """Test that MCP server has the expected tools."""
    try:
        from gdrive_mcp.mcp_server import mcp

        # Check that the server has the expected tools
        expected_tools = [
            "search_documents",
            "create_document",
            "get_document",
            "update_document",
            "delete_document",
            "list_folders",
            "list_drives",
            "copy_document",
            "list_customer_files",
        ]

        server_tools = [tool.name for tool in mcp.tools]

        for tool_name in expected_tools:
            if tool_name in server_tools:
                print(f"✓ Tool '{tool_name}' found")
            else:
                print(f"✗ Tool '{tool_name}' not found")
                return False

        print(f"✓ All {len(expected_tools)} expected tools found")
        return True

    except Exception as e:
        print(f"✗ MCP server tools test error: {e}")
        return False


def main():
    """Run all tests."""
    print("Testing Google Drive MCP Server...\n")

    tests = [
        ("Module Imports", test_imports),
        ("Model Creation", test_model_creation),
        ("MCP Server Tools", test_mcp_server_tools),
    ]

    passed = 0
    total = len(tests)

    for test_name, test_func in tests:
        print(f"Running {test_name}...")
        if test_func():
            passed += 1
            print(f"✓ {test_name} passed\n")
        else:
            print(f"✗ {test_name} failed\n")

    print(f"Test Results: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! Google Drive MCP Server is ready to use.")
        return 0
    else:
        print("❌ Some tests failed. Please check the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
