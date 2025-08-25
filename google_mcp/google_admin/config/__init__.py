from typing import Dict, List

from fastapi_azure_auth import SingleTenantAzureAuthorizationCodeBearer
from pydantic_settings import BaseSettings, SettingsConfigDict

from .google import GoogleAdminSettings

__all__ = ["settings"]


class AppSettings(BaseSettings):
    """Settings for the Google Admin MCP application."""

    google: GoogleAdminSettings

    log_config_file: str = "logging.conf"
    cors_origin_regex: str = ""
    tags_metadata: list[dict[str, str]] = [
        {
            "name": "users",
            "description": "Manage users in the Google Admin MCP.",
        }
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )


settings = AppSettings()
