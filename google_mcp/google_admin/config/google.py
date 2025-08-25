from pydantic import BaseModel


class GoogleAdminSettings(BaseModel):
    """Settings for Google Admin SDK configuration."""

    log_config_file: str = "logging.conf"

    # Google Admin SDK scopes
    SCOPES: list[str] = [
        "https://www.googleapis.com/auth/admin.directory.user",
        "https://www.googleapis.com/auth/admin.directory.rolemanagement",
        "https://www.googleapis.com/auth/admin.directory.group",
        # Google Drive scopes
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive.metadata.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
        # Google Docs scope for editing Docs content
        # "https://www.googleapis.com/auth/documents",
    ]

    ADMIN_EMAIL: str
    TYPE: str
    PROJECT_ID: str
    PRIVATE_KEY_ID: str
    PRIVATE_KEY: str
    CLIENT_EMAIL: str
    CLIENT_ID: str
    AUTH_URI: str
    TOKEN_URI: str
    AUTH_PROVIDER_X509_CERT_URL: str
    CLIENT_X509_CERT_URL: str
    UNIVERSE_DOMAIN: str
