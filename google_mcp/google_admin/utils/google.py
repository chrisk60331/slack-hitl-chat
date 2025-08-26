import logging
import secrets
import string

from google.oauth2 import service_account

from ..config import settings

logger = logging.getLogger(__name__)


def create_app_config_dict() -> dict:
    """
    Create a dictionary with the configuration for the Google service account app.

    This function retrieves environment variables needed for Google service account
    authentication and formats them into the required configuration dictionary.

    Returns:
        dict: A dictionary containing all required Google service account configuration fields:
            - type: The type of account (usually "service_account")
            - project_id: The Google Cloud project ID
            - private_key_id: The ID of the private key
            - private_key: The actual private key content (PEM format)
            - client_email: Service account email address
            - client_id: Service account unique identifier
            - auth_uri: Google's OAuth2 auth URI
            - token_uri: Google's OAuth2 token URI
            - auth_provider_x509_cert_url: Google's cert provider URL
            - client_x509_cert_url: Service account's cert URL
            - universe_domain: Google API universe domain

    Note:
        All values are retrieved from environment variables with matching names
    """
    google_config = {
        "type": settings.google.TYPE,
        "project_id": settings.google.PROJECT_ID,
        "private_key_id": settings.google.PRIVATE_KEY_ID,
        "private_key": settings.google.PRIVATE_KEY.replace("\\n", "\n"),
        "client_email": settings.google.CLIENT_EMAIL,
        "client_id": settings.google.CLIENT_ID,
        "auth_uri": settings.google.AUTH_URI,
        "token_uri": settings.google.TOKEN_URI,
        "auth_provider_x509_cert_url": settings.google.AUTH_PROVIDER_X509_CERT_URL,
        "client_x509_cert_url": settings.google.CLIENT_X509_CERT_URL,
        "universe_domain": settings.google.UNIVERSE_DOMAIN,
    }
    # Redact sensitive fields before logging
    redacted_config = google_config.copy()
    for key in ["private_key", "client_email", "client_id", "private_key_id"]:
        if redacted_config.get(key):
            redacted_config[key] = "[REDACTED]"
    logger.info(f"Google config: {redacted_config}")
    return google_config


def get_google_credentials() -> service_account.Credentials:
    """
    Get Google credentials using service account authentication.

    This function:
    1. Creates a service account configuration dictionary
    2. Initializes credentials with specified OAuth scopes
    3. Optionally configures domain-wide delegation if admin email is provided

    Returns:
        service_account.Credentials: Initialized Google service account credentials
            with directory user management scope and optional domain delegation

    Raises:
        ValueError: If required environment variables are missing
        google.auth.exceptions.RefreshError: If credentials cannot be initialized

    Note:
        Requires environment variables for service account configuration and
        optionally GOOGLE_ADMIN_EMAIL for domain-wide delegation
    """
    logger.debug("Creating service account configuration dictionary")
    creds_dict = create_app_config_dict()

    logger.info("Initializing Google service account credentials")
    logger.debug("Using scopes: %s", settings.google.SCOPES)

    try:
        credentials = service_account.Credentials.from_service_account_info(
            info=creds_dict, scopes=settings.google.SCOPES
        )
        logger.debug("Successfully created base credentials")
    except ValueError:
        logger.error(
            "Failed to create credentials: missing or invalid configuration"
        )
        raise

    # If using domain-wide delegation, add subject
    if settings.google.ADMIN_EMAIL:
        credentials = credentials.with_subject(settings.google.ADMIN_EMAIL)

    return credentials


def generate_secure_password() -> str:
    """Generate a secure random password meeting complexity requirements."""
    length = 12
    # Ensure at least one of each required character type
    password = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(string.punctuation),
    ]
    # Fill the rest with random characters
    password.extend(
        secrets.choice(
            string.ascii_letters + string.digits + string.punctuation
        )
        for _ in range(length - len(password))
    )
    # Shuffle the password
    return "".join(secrets.SystemRandom().sample(password, len(password)))
