#!/usr/bin/env python3
"""Example usage of Google Drive MCP functionality.

This script demonstrates how to use the Google Drive MCP tools
for document search, creation, and management.
"""

import json
from typing import Any

# Example function calls that would be made by an MCP client
# These represent the tool invocations that would happen in practice


def example_search_documents() -> dict[str, Any]:
    """Example of searching for documents."""

    # This would be the request sent to the search_documents tool
    search_request = {
        "query": "project plan",
        "file_types": ["document", "spreadsheet"],
        "max_results": 20,
        "include_shared": True,
    }

    print("🔍 Example: Search for documents")
    print(f"Request: {json.dumps(search_request, indent=2)}")
    print()

    # Example response (what the tool would return)
    example_response = {
        "query": "project plan",
        "total_results": 3,
        "results": [
            {
                "id": "doc_123",
                "name": "Q1 Project Plan",
                "mime_type": "application/vnd.google-apps.document",
                "owners": ["user@example.com"],
                "created_time": "2024-01-15T10:00:00Z",
                "modified_time": "2024-01-20T14:30:00Z",
                "web_view_link": "https://docs.google.com/document/d/doc_123/edit",
                "permissions": [
                    {
                        "email": "team@example.com",
                        "role": "writer",
                        "type": "user",
                    }
                ],
            },
            {
                "id": "sheet_456",
                "name": "Project Timeline",
                "mime_type": "application/vnd.google-apps.spreadsheet",
                "owners": ["user@example.com"],
                "created_time": "2024-01-10T09:00:00Z",
                "modified_time": "2024-01-18T16:45:00Z",
                "web_view_link": "https://docs.google.com/spreadsheets/d/sheet_456/edit",
                "permissions": [],
            },
        ],
    }

    print("Response:")
    print(json.dumps(example_response, indent=2))
    print()
    return example_response


def example_create_document() -> dict[str, Any]:
    """Example of creating a new document."""

    # This would be the request sent to the create_document tool
    create_request = {
        "title": "Meeting Notes - January 2024",
        "document_type": "document",
        "content": "Agenda:\n1. Project updates\n2. Resource allocation\n3. Next steps",
        "permissions": ["team@example.com", "stakeholder@example.com"],
    }

    print("📝 Example: Create a new document")
    print(f"Request: {json.dumps(create_request, indent=2)}")
    print()

    # Example response (what the tool would return)
    example_response = {
        "message": "Document created successfully",
        "document": {
            "id": "new_doc_789",
            "name": "Meeting Notes - January 2024",
            "mime_type": "application/vnd.google-apps.document",
            "web_view_link": "https://docs.google.com/document/d/new_doc_789/edit",
            "created_time": "2024-01-25T11:00:00Z",
        },
    }

    print("Response:")
    print(json.dumps(example_response, indent=2))
    print()
    return example_response


def example_get_document() -> dict[str, Any]:
    """Example of retrieving document information."""

    # This would be the request sent to the get_document tool
    get_request = {"document_id": "doc_123", "include_content": True}

    print("📄 Example: Get document details")
    print(f"Request: {json.dumps(get_request, indent=2)}")
    print()

    # Example response (what the tool would return)
    example_response = {
        "id": "doc_123",
        "name": "Q1 Project Plan",
        "mime_type": "application/vnd.google-apps.document",
        "owners": ["user@example.com"],
        "created_time": "2024-01-15T10:00:00Z",
        "modified_time": "2024-01-20T14:30:00Z",
        "size": "2048",
        "web_view_link": "https://docs.google.com/document/d/doc_123/edit",
        "permissions": [
            {"email": "team@example.com", "role": "writer", "type": "user"}
        ],
        "content": "Q1 Project Plan\n\nExecutive Summary:\nThis document outlines the key initiatives...",
    }

    print("Response:")
    print(json.dumps(example_response, indent=2))
    print()
    return example_response


def example_list_folders() -> dict[str, Any]:
    """Example of listing folders."""

    # This would be the request sent to the list_folders tool
    list_request = {
        "parent_folder_id": "root",
        "max_results": 10,
        "include_shared": False,
    }

    print("📁 Example: List folders")
    print(f"Request: {json.dumps(list_request, indent=2)}")
    print()

    # Example response (what the tool would return)
    example_response = {
        "total_folders": 4,
        "folders": [
            {
                "id": "folder_1",
                "name": "Projects",
                "created_time": "2024-01-01T00:00:00Z",
                "modified_time": "2024-01-25T12:00:00Z",
                "web_view_link": "https://drive.google.com/drive/folders/folder_1",
                "owners": ["user@example.com"],
            },
            {
                "id": "folder_2",
                "name": "Team Documents",
                "created_time": "2024-01-01T00:00:00Z",
                "modified_time": "2024-01-24T15:30:00Z",
                "web_view_link": "https://drive.google.com/drive/folders/folder_2",
                "owners": ["user@example.com"],
            },
        ],
    }

    print("Response:")
    print(json.dumps(example_response, indent=2))
    print()
    return example_response


def example_update_document() -> dict[str, Any]:
    """Example of updating a document."""

    # This would be the request sent to the update_document tool
    update_request = {
        "document_id": "doc_123",
        "title": "Q1 Project Plan - Updated",
        "content": "Updated content with latest information...",
        "permissions": ["new_team_member@example.com"],
    }

    print("✏️ Example: Update document")
    print(f"Request: {json.dumps(update_request, indent=2)}")
    print()

    # Example response (what the tool would return)
    example_response = {
        "message": "Document updated successfully",
        "document_id": "doc_123",
    }

    print("Response:")
    print(json.dumps(example_response, indent=2))
    print()
    return example_response


def example_delete_document() -> dict[str, Any]:
    """Example of deleting a document."""

    # This would be the request sent to the delete_document tool
    delete_request = {
        "document_id": "old_doc_999",
        "permanent": False,  # Move to trash instead of permanent deletion
    }

    print("🗑️ Example: Delete document")
    print(f"Request: {json.dumps(delete_request, indent=2)}")
    print()

    # Example response (what the tool would return)
    example_response = {
        "message": "Document moved to trash",
        "document_id": "old_doc_999",
    }

    print("Response:")
    print(json.dumps(example_response, indent=2))
    print()
    return example_response


def main():
    """Run all examples."""
    print("🚀 Google Drive MCP Tool Examples")
    print("=" * 50)
    print()

    # Run all examples
    examples = [
        example_search_documents,
        example_create_document,
        example_get_document,
        example_list_folders,
        example_update_document,
        example_delete_document,
    ]

    for example_func in examples:
        example_func()
        print("-" * 50)
        print()

    print("✅ All examples completed!")
    print("\nThese examples show how the Google Drive MCP tools would be used")
    print("in practice by an MCP client (like an AI agent) to interact with")
    print("Google Drive documents and folders.")


if __name__ == "__main__":
    main()
