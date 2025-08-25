import logging

import gytrash
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import settings
from .routers.api.v1 import users_router

log = logging.getLogger()

gytrash.setup_logging(
    log,
    log_level=30,
    log_from_botocore=False,
    log_to_slack=False,
    logging_conf_file_path=settings.log_config_file,
)

log.info("Test info message")
log.debug("Test debug message")

app = FastAPI(
    title="Google Admin MCP",
    description="A FastAPI server for managing Google Workspace users through the Admin Directory API",
    version=__version__,
    debug=True,
    swagger_ui_oauth2_redirect_url="/oauth2-redirect",
    swagger_ui_init_oauth={
        "usePkceWithAuthorizationCodeGrant": True,
        "clientId": settings.azure.openapi_client_id,
    },
    openapi_tags=settings.tags_metadata,
)

if settings.cors_origin_regex:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


app.include_router(users_router, prefix="/api/v1")


@app.get("/health")
def healthcheck():
    return {"status": "ok"}
