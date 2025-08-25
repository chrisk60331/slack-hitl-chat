"""User management routes for Google Admin MCP."""

import logging

from fastapi import APIRouter, HTTPException, Security

from ....config import azure_scheme
from ....models import (
    AddRoleRequest,
    AddUserRequest,
    ListUsersRequest,
    RemoveRoleRequest,
    UserKeyRequest,
)
from ....schema.users import User
from ....services import UserService

router = APIRouter(prefix="/users", tags=["users"])
logger = logging.getLogger(__name__)


@router.post(
    "/list",
    summary="List users in a domain",
    description="List users in a domain",
    response_model=list[str],
    dependencies=[Security(azure_scheme)],
)
async def list_users(
    request: ListUsersRequest,
) -> dict:
    """List users in a domain."""
    try:
        service = UserService()
        logger.info(f"Listing users for domain: {request.domain}")
        return service.list_users(
            request.domain,
            maxResults=request.maxResults,
            orderBy=request.orderBy,
        )
    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/add",
    summary="Add a new user",
    description="Add a new user",
    response_model=User,
    dependencies=[Security(azure_scheme)],
)
async def add_user(request: AddUserRequest) -> dict:
    """Create a new user."""
    try:
        service = UserService()
        return service.add_user(
            request.primary_email, request.first_name, request.last_name
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/get",
    summary="Get a user by key",
    description="Get a user by key",
    response_model=User,
    dependencies=[Security(azure_scheme)],
)
async def get_user(request: UserKeyRequest) -> dict:
    """Get detailed information about a specific user."""
    try:
        service = UserService()
        return service.get_user(request.user_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/suspend",
    summary="Suspend a user account",
    description="Suspend a user account",
    response_model=str,
    dependencies=[Security(azure_scheme)],
)
async def suspend_user(request: UserKeyRequest) -> dict:
    """Suspend a user account."""
    try:
        service = UserService()
        return service.suspend_user(request.user_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/unsuspend",
    summary="Unsuspend a user account",
    description="Unsuspend a user account",
    response_model=str,
    dependencies=[Security(azure_scheme)],
)
async def unsuspend_user(request: UserKeyRequest) -> dict:
    """Unsuspend a user account."""
    try:
        service = UserService()
        return service.unsuspend_user(request.user_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/roles/add",
    summary="Add an AWS account role to the user",
    description="Add an AWS account role to the user",
    dependencies=[Security(azure_scheme)],
)
async def add_role(request: AddRoleRequest) -> dict:
    """Add an AWS role to a user's profile."""
    try:
        service = UserService()
        return service.add_user_aws_roles_from_request(request)
    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/roles/remove",
    summary="Remove an AWS account role from the user",
    description="Remove an AWS account role from the user",
    dependencies=[Security(azure_scheme)],
)
async def remove_role(request: RemoveRoleRequest) -> dict:
    """Remove an AWS role from a user's profile."""
    try:
        service = UserService()
        return service.remove_user_aws_roles_from_request(request)
    except Exception as e:
        logger.error(e)
        raise HTTPException(status_code=400, detail=str(e))
