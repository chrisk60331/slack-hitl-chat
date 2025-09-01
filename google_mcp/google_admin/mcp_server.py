"""Google Admin MCP Server.

This module provides an MCP server for Google Admin operations including
user management, role management, and other administrative tasks.
"""

import os
import sys

from fastmcp import FastMCP
from fastmcp.server.auth import BearerAuthProvider
from fastmcp.server.auth.providers.bearer import RSAKeyPair

sys.path.append("/var/task/")
# Add the google_mcp directory to the path for local development
current_dir = os.path.dirname(os.path.abspath(__file__))
google_mcp_dir = os.path.join(current_dir, "..")
sys.path.append(google_mcp_dir)

from google_admin.models import (
    AddRoleRequest,
    AddUserRequest,
    ListUsersRequest,
    RemoveRoleRequest,
    UserKeyRequest,
)
from google_admin.services import UserService

# For stdio transport, we don't need HTTP-based authentication
# Generate a new key pair for development/testing (keeping for compatibility)
key_pair = RSAKeyPair.generate()

# Configure the auth provider with the public key (optional for stdio)
auth = BearerAuthProvider(
    public_key=key_pair.public_key,
    issuer="https://dev.example.com",
    audience="google_admin",
)

# For stdio transport, we can remove auth or keep it minimal
mcp = FastMCP(
    "Google Admin MCP Server",
    # auth=auth,  # Commented out for stdio transport
    dependencies=["google_admin@./google_admin"],
)


@mcp.tool(
    name="list_users",
    description="List users in a Google Workspace domain.",
    tags=["users", "list", "google workspace"],
)
def list_users(request: ListUsersRequest) -> list[str]:
    """
    List users in a Google Workspace domain.

    Args:
        request (ListUsersRequest):
            domain (str): The domain to list users from.
            maxResults (int, optional): Maximum number of results to return.
            orderBy (str, optional): Field to order results by.
    Returns:
        List[str]: List of user emails and names in the domain.
    """
    service = UserService()
    return service.list_users(
        request.domain,
        maxResults=request.maxResults,
        orderBy=request.orderBy,
    )


@mcp.tool(
    name="add_user",
    description="Create a new user in Google Workspace.",
    tags=["users", "add", "google workspace"],
)
def add_user(request: AddUserRequest) -> dict:
    """
    Create a new user in Google Workspace.

    Args:
        request (AddUserRequest):
            primary_email (str): The user's primary email address.
            first_name (str): The user's first name.
            last_name (str): The user's last name.
    Returns:
        dict: The created user's details.
    """
    service = UserService()
    return service.add_user(
        request.primary_email, request.first_name, request.last_name
    )


@mcp.tool(
    name="get_user",
    description="Get detailed information about a specific user.",
    tags=["users", "get", "google workspace"],
)
def get_user(request: UserKeyRequest) -> dict:
    """
    Retrieve detailed information about a specific user.

    Args:
        request (UserKeyRequest):
            user_key (str): The user's email address or unique ID.
    Returns:
        dict: The user's detailed information.
    """
    service = UserService()
    return service.get_user(request.user_key)


@mcp.tool(
    name="suspend_user",
    description="Suspend a user account in Google Workspace.",
    tags=["users", "suspend", "google workspace"],
)
def suspend_user(request: UserKeyRequest) -> dict:
    """
    Suspend a user account in Google Workspace.

    Args:
        request (UserKeyRequest):
            user_key (str): The user's email address or unique ID.
    Returns:
        dict: Contains a confirmation message and the user's email and name.
    """
    service = UserService()
    return service.suspend_user(request.user_key)


@mcp.tool(
    name="unsuspend_user",
    description="Unsuspend a user account in Google Workspace.",
    tags=["users", "unsuspend", "google workspace"],
)
def unsuspend_user(request: UserKeyRequest) -> dict:
    """
    Unsuspend a user account in Google Workspace.

    Args:
        request (UserKeyRequest):
            user_key (str): The user's email address or unique ID.
    Returns:
        dict: Contains a confirmation message and the user's email and name.
    """
    service = UserService()
    return service.unsuspend_user(request.user_key)


@mcp.tool(
    name="get_amazon_roles",
    description="Retrieve Amazon roles from a user's profile.",
    tags=["users", "roles", "google workspace"],
)
def get_amazon_roles(request: UserKeyRequest) -> dict:
    """
    Retrieve Amazon (AWS) roles from a user's Google Workspace profile.

    Args:
        request (UserKeyRequest):
            user_key (str): The user's email address or unique ID.
    Returns:
        dict: Contains the user's email, list of AWS roles, and a boolean indicating if any roles exist.
    """
    service = UserService()
    return service.get_user_aws_roles(request.user_key)


@mcp.tool(
    name="add_amazon_role",
    description="Add a new AWS account and role to a user's profile.",
    tags=["users", "roles", "google workspace"],
)
def add_amazon_role(request: AddRoleRequest) -> dict:
    """
    Add a new AWS role to a user's Google Workspace profile. Account ID is derived from provided ARNs.

    Args:
        request (AddRoleRequest):
            user_key (str): The user's email address or unique ID.
            admin_role (str): The AWS role ARN to add.
            identity_provider (str): The SAML identity provider ARN.
    Returns:
        dict: Contains a confirmation message, the user's email, and the list of AWS roles after the operation.
    """
    service = UserService()

    return service.add_user_aws_roles_from_request(request)


@mcp.tool(
    name="remove_amazon_role",
    description="Remove an AWS account and role from a user's profile.",
    tags=["users", "roles", "google workspace"],
)
def remove_amazon_role(request: RemoveRoleRequest) -> dict:
    """
    Remove an AWS role from a user's Google Workspace profile.

    Args:
        request (RemoveRoleRequest):
            user_key (str): The user's email address or unique ID.
            admin_role (str): The AWS role ARN to remove.
            identity_provider (str): The SAML identity provider ARN.
    Returns:
        dict: Contains a confirmation message, the user's email, and the list of AWS roles after the operation.
    """
    service = UserService()
    return service.remove_user_aws_roles_from_request(request)


token = key_pair.create_token(
    subject="dev-user",
    issuer="https://dev.example.com",
    audience="google_admin",
    scopes=["read", "write"],
)


if __name__ == "__main__":
    # Use stdio transport for MCP client compatibility
    mcp.run(transport="stdio")
