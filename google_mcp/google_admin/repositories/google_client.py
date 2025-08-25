import logging

from fastapi import HTTPException
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from ..utils.google import generate_secure_password, get_google_credentials

logger = logging.getLogger(__name__)

# Google Admin SDK configuration
SCOPES = [
    "https://www.googleapis.com/auth/admin.directory.user",
    "https://www.googleapis.com/auth/admin.directory.group",
]


# def load_saved_credentials() -> Credentials:
#     """Load and validate Google credentials from environment variable."""
#     try:
#         token_json = base64.b64decode(settings.GOOGLE_TOKEN_JSON).decode("utf-8")
#         credentials_dict = json.loads(token_json)
#         return Credentials.from_authorized_user_info(credentials_dict, settings.SCOPES)
#     except Exception as e:
#         raise HTTPException(
#             status_code=500, detail=f"Failed to load authentication token: {str(e)}"
#         )


class GoogleAdminClient:
    """Client for interacting with Google Admin Directory API."""

    def __init__(self):
        """Initialize the Google Admin client."""
        logger.debug("Getting Google credentials")
        self.credentials: Credentials = get_google_credentials()
        self.service = build("admin", "directory_v1", credentials=self.credentials)

    def list_users(
        self, domain: str, maxResults: int = 10, orderBy: str = "email"
    ) -> list[dict]:
        """List users in a domain."""
        try:
            logger.debug(f"Listing users in domain: {domain}")
            logger.debug(f"Credentials: {self.credentials}")
            logger.debug(f"Service: {self.service}")

            response = (
                self.service.users()
                .list(domain=domain, maxResults=maxResults, orderBy=orderBy)
                .execute()
            )
            return response.get("users", [])
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def add_user(self, primary_email: str, first_name: str, last_name: str) -> dict:
        """Create a new user."""
        try:
            password = generate_secure_password()
            user = {
                "primaryEmail": primary_email,
                "password": password,
                "name": {
                    "givenName": first_name,
                    "familyName": last_name,
                    "fullName": f"{first_name} {last_name}",
                },
                "changePasswordAtNextLogin": True,
            }
            response = self.service.users().insert(body=user).execute()
            response["initial_password"] = password
            return response
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def get_user(
        self, user_key: str, projection: str = "full", custom_field_mask: str = None
    ) -> dict:
        """Get detailed information about a specific user."""
        try:
            params = {"userKey": user_key, "projection": projection}
            if custom_field_mask:
                params["customFieldMask"] = custom_field_mask
            return self.service.users().get(**params).execute()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def suspend_user(self, user_key: str) -> dict:
        """Suspend a user account."""
        try:
            return (
                self.service.users()
                .update(userKey=user_key, body={"suspended": True})
                .execute()
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def unsuspend_user(self, user_key: str) -> dict:
        """Unsuspend a user account."""
        try:
            return (
                self.service.users()
                .update(userKey=user_key, body={"suspended": False})
                .execute()
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def update_user(self, user_key: str, update_body: dict) -> dict:
        """Update a user's information including custom schemas."""
        try:
            return (
                self.service.users()
                .update(userKey=user_key, body=update_body)
                .execute()
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
