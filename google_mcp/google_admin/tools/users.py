from ..models import AddUserRequest, ListUsersRequest, UserKeyRequest
from ..schema.users import User
from ..services import UserService


def list_users(request: ListUsersRequest) -> list[str]:
    """List users in a domain."""
    service = UserService()
    return service.list_users(
        request.domain,
        maxResults=request.maxResults,
        orderBy=request.orderBy,
    )


def add_user(request: AddUserRequest) -> User:
    """Create a new user."""
    service = UserService()
    return service.add_user(
        request.primary_email, request.first_name, request.last_name
    )


def get_user(request: UserKeyRequest) -> User:
    """Get detailed information about a specific user."""
    service = UserService()
    return service.get_user(request.user_key)


def suspend_user(request: UserKeyRequest) -> str:
    """Suspend a user account."""
    service = UserService()
    return service.suspend_user(request.user_key)


def unsuspend_user(request: UserKeyRequest) -> str:
    """Unsuspend a user account."""
    service = UserService()
    return service.unsuspend_user(request.user_key)
