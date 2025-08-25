"""User service for Google Admin MCP."""

import logging
import re

from ..models import AddRoleRequest, RemoveRoleRequest
from ..repositories.google_client import GoogleAdminClient

logger = logging.getLogger(__name__)


class UserService:
    """Service for managing Google Workspace users."""

    def __init__(self):
        """Initialize the user service.

        Args:
            client: Optional Google Admin client. If not provided, a new one will be created.
        """
        logger.info("Initializing user service")
        self.client = GoogleAdminClient()

    def list_users(
        self, domain: str, maxResults: int | None = None, orderBy: str | None = None
    ) -> dict:
        """List users in a domain.

        Args:
            domain: The domain to list users from.
            maxResults: Optional maximum number of results to return.
            orderBy: Optional field to order results by. default: email.

        Returns:
            Dict containing either a list of users or a "no users found" message.
        """
        logger.info(f"Listing users for domain: {domain}")
        users = self.client.list_users(
            domain, maxResults=maxResults or 10, orderBy=orderBy or "email"
        )

        if not users:
            return {"message": "No users found."}

        user_list = [
            f"{user['primaryEmail']} ({user.get('name', {}).get('fullName', 'Unknown')})"
            for user in users
        ]

        return user_list

    def add_user(self, primary_email: str, first_name: str, last_name: str) -> dict:
        """Create a new user.

        Args:
            primary_email: The user's primary email address.
            first_name: The user's first name.
            last_name: The user's last name.

        Returns:
            Dict containing the created user's details and initial password.
        """
        response = self.client.add_user(primary_email, first_name, last_name)
        return {
            "message": "User created successfully",
            "email": response["primaryEmail"],
            "name": response["name"]["fullName"],
            "initial_password": response["initial_password"],
        }

    def get_user(self, user_key: str) -> dict:
        """Get detailed information about a specific user.

        Args:
            user_key: The user's email address or ID.

        Returns:
            Dict containing the user's detailed information.
        """
        response = self.client.get_user(user_key)
        return {
            "email": response["primaryEmail"],
            "name": response.get("name", {}).get("fullName", "Unknown"),
            "id": response["id"],
            "is_admin": response.get("isAdmin", False),
            "suspended": response.get("suspended", False),
            "last_login": response.get("lastLoginTime", "Never"),
            "created": response["creationTime"],
            "org_unit": response.get("orgUnitPath", "Default"),
            "aliases": response.get("aliases", []),
            "2fa_enabled": response.get("isEnrolledIn2Sv", False),
            "2fa_enforced": response.get("isEnforcedIn2Sv", False),
            "ip_whitelisted": response.get("ipWhitelisted", False),
            "recovery_email": response.get("recoveryEmail", "Not set"),
            "recovery_phone": response.get("recoveryPhone", "Not set"),
            "suspension_reason": response.get("suspensionReason", "Not specified"),
        }

    def suspend_user(self, user_key: str) -> dict:
        """Suspend a user account.

        Args:
            user_key: The user's email address or ID.

        Returns:
            Dict containing the suspended user's details.
        """
        response = self.client.suspend_user(user_key)
        return {
            "message": "User suspended successfully",
            "email": response["primaryEmail"],
            "name": response["name"]["fullName"],
        }

    def unsuspend_user(self, user_key: str) -> dict:
        """Unsuspend a user account.

        Args:
            user_key: The user's email address or ID.

        Returns:
            Dict containing the unsuspended user's details.
        """
        response = self.client.unsuspend_user(user_key)
        return {
            "message": "User unsuspended successfully",
            "email": response["primaryEmail"],
            "name": response["name"]["fullName"],
        }

    def get_user_aws_roles(self, user_key: str) -> dict:
        """Get AWS roles for a specific user from their Google Workspace custom schema.

        Args:
            user_key: The user's email address or ID.

        Returns:
            Dict containing the user's AWS roles information.
        """
        user = self.client.get_user(
            user_key, projection="full", custom_field_mask="Amazon"
        )

        roles = []
        if "customSchemas" in user and "Amazon" in user["customSchemas"]:
            roles = user["customSchemas"]["Amazon"].get("Role", [])

        formatted_roles = []

        for role in roles:
            role_value = role["value"]
            if re.match("([a-z0-9]*:*)*/[a-zA-Z-]*", role_value):
                account = role_value.split(":")[4]
                saml_provider = role_value.split(",")[-1]
                role_name = role_value.split(",")[-2]

                formatted_roles.append(
                    {
                        "account": account,
                        "saml_provider": saml_provider,
                        "role": role_name,
                    }
                )

        return {
            "email": user["primaryEmail"],
            "roles": formatted_roles,
            "has_roles": bool(formatted_roles),
        }

    def add_user_aws_roles(
        self, user_key: str, admin_role: str, identity_provider: str
    ) -> dict:
        """Add AWS roles to a user's Google Workspace custom schema.

        Args:
            user_key: The user's email address or ID.
            admin_role: The AWS role ARN to add.
            identity_provider: The SAML identity provider ARN.
            identity_provider: The SAML identity provider ARN.

        Returns:
            Dict containing confirmation message and updated roles.
        """
        # Get current user data
        # Fetch raw roles from the user's custom schema
        user = self.client.get_user(
            user_key, projection="full", custom_field_mask="Amazon"
        )
        roles_raw = []
        if "customSchemas" in user and "Amazon" in user["customSchemas"]:
            roles_raw = user["customSchemas"]["Amazon"].get("Role", [])

        # Create new role entry - format: role_arn,identity_provider_arn
        new_role_value = f"{admin_role},{identity_provider}"

        if not re.match("([a-z0-9]*:*)*/[a-zA-Z-]*", new_role_value):
            return {
                "message": f"Invalid role format {new_role_value}, must be ARN format aws::::",
                "email": user_key,
                "roles": self.get_user_aws_roles(user_key)["roles"],
            }

        # Check if role already exists for the same AWS account (derived from ARNs)
        def _extract_account(arn: str) -> str | None:
            m = re.match(r"^arn:aws:iam::(\d{12}):", arn)
            return m.group(1) if m else None

        requested_account = _extract_account(admin_role) or _extract_account(
            identity_provider
        )

        existing_accounts = []
        for role in roles_raw:
            value = role.get("value", "")
            parts = value.split(",")
            role_arn = parts[0].strip() if parts else ""
            idp_arn = parts[1].strip() if len(parts) > 1 else ""
            acct = _extract_account(role_arn) or _extract_account(idp_arn)
            if acct:
                existing_accounts.append(acct)

        if requested_account and requested_account in existing_accounts:
            return {
                "message": "AWS role already exists for user",
                "email": user_key,
                "roles": self.get_user_aws_roles(user_key)["roles"],
            }

        # Add new role
        new_role = {"value": new_role_value}
        roles_raw.append(new_role)

        # Update user with new roles
        update_body = {"customSchemas": {"Amazon": {"Role": roles_raw}}}

        response = self.client.update_user(user_key, update_body)

        return {
            "message": f"Successfully added AWS role {admin_role}",
            "email": user_key,
            "roles": self.get_user_aws_roles(user_key)["roles"],
            "response": response,
        }

    def remove_user_aws_roles(
        self, user_key: str, admin_role: str, identity_provider: str
    ) -> dict:
        """Remove AWS roles from a user's Google Workspace custom schema.

        Args:
            user_key: The user's email address or ID.
            admin_role: The AWS role ARN to remove.
            identity_provider: The SAML identity provider ARN.
            identity_provider: The SAML identity provider ARN.

        Returns:
            Dict containing confirmation message and updated roles.
        """
        # Get current user data
        # Fetch raw roles from the user's custom schema
        user = self.client.get_user(
            user_key, projection="full", custom_field_mask="Amazon"
        )
        roles_raw = []
        if "customSchemas" in user and "Amazon" in user["customSchemas"]:
            roles_raw = user["customSchemas"]["Amazon"].get("Role", [])

        # Create role entry to remove - format: role_arn,identity_provider_arn
        role_to_remove = f"{admin_role},{identity_provider}"

        # Filter out the exact role to remove
        filtered_roles = [r for r in roles_raw if r.get("value") != role_to_remove]

        if len(filtered_roles) == len(roles_raw):
            return {
                "message": (
                    f"AWS role not found for user. Found {len(roles_raw)} roles. "
                    f"Role to remove: {role_to_remove}"
                ),
                "email": user_key,
                "roles": self.get_user_aws_roles(user_key)["roles"],
            }

        # Update user with filtered roles
        update_body = {"customSchemas": {"Amazon": {"Role": filtered_roles}}}

        response = self.client.update_user(user_key, update_body)

        return {
            "message": (f"Successfully removed AWS role {admin_role}"),
            "email": user_key,
            "roles": self.get_user_aws_roles(user_key)["roles"],
        }

    def add_user_aws_roles_from_request(self, request: AddRoleRequest) -> dict:
        """Add AWS roles using a validated request model.

        Args:
            request: Validated `AddRoleRequest` containing all required fields.

        Returns:
            Dict with the operation outcome.
        """
        return self.add_user_aws_roles(
            user_key=request.user_key,
            admin_role=request.admin_role,
            identity_provider=request.identity_provider,
        )

    def remove_user_aws_roles_from_request(self, request: RemoveRoleRequest) -> dict:
        """Remove AWS roles using a validated request model.

        Args:
            request: Validated `RemoveRoleRequest` containing all required fields.

        Returns:
            Dict with the operation outcome.
        """
        return self.remove_user_aws_roles(
            user_key=request.user_key,
            admin_role=request.admin_role,
            identity_provider=request.identity_provider,
        )
