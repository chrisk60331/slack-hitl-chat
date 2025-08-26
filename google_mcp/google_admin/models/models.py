"""Pydantic models for request validation.

This module defines request schemas for Google Admin operations using Pydantic v2.
It includes strict validation for AWS-related fields used when managing roles.
"""

from typing import Annotated

from pydantic import BaseModel, EmailStr, StringConstraints


class ListUsersRequest(BaseModel):
    """Request model for listing users."""

    domain: str
    maxResults: int | None = None
    orderBy: str | None = None


class AddUserRequest(BaseModel):
    """Request model for adding a new user."""

    primary_email: EmailStr
    first_name: str
    last_name: str


class UserKeyRequest(BaseModel):
    """Request model for user key operations."""

    user_key: str


class AddRoleRequest(BaseModel):
    """Request model for adding AWS roles to a user."""

    user_key: str
    admin_role: Annotated[
        str,
        StringConstraints(
            pattern=r"^arn:aws:iam::\d{12}:role/[a-zA-Z0-9_-]+$"
        ),
    ]
    identity_provider: Annotated[
        str,
        StringConstraints(
            pattern=r"^arn:aws:iam::\d{12}:saml-provider/[a-zA-Z0-9_-]+$"
        ),
    ]


class RemoveRoleRequest(BaseModel):
    """Request model for removing AWS roles from a user."""

    user_key: str
    admin_role: Annotated[
        str,
        StringConstraints(
            pattern=r"^arn:aws:iam::\d{12}:role/[a-zA-Z0-9_-]+$"
        ),
    ]
    identity_provider: Annotated[
        str,
        StringConstraints(
            pattern=r"^arn:aws:iam::\d{12}:saml-provider/[a-zA-Z0-9_-]+$"
        ),
    ]
