"""
FastAPI application entrypoint.

- Lifespan event handler for startup/shutdown
- CORS middleware
- Structured logging via structlog (see app.logging_setup)
- Router registration

Schema management is owned by Alembic. We deliberately do NOT call
``SQLModel.metadata.create_all()`` at startup (it races migrations and
silently drifts the schema). The opt-in dev escape hatch is
``DEV_AUTOCREATE_TABLES=true``.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import create_db_and_tables
from app.logging_setup import get_logger, setup_logging
from app.routers import admin, alerts, domains, health, subscriptions

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    settings = get_settings()
    logger.info("app_starting", app=settings.APP_NAME, version=settings.APP_VERSION,
                env=settings.APP_ENV)

    if settings.DEV_AUTOCREATE_TABLES:
        # Dev-only convenience. In every other environment Alembic owns
        # the schema and this branch must stay dormant.
        create_db_and_tables()
        logger.warning("dev_autocreate_tables_enabled",
                       reason="Schema created via SQLModel.metadata. "
                       "DO NOT enable in production.")
    else:
        logger.info("schema_owned_by_alembic")

    yield

    logger.info("app_shutting_down", app=settings.APP_NAME)


settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI-powered regulatory monitoring platform",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(domains.router)
app.include_router(subscriptions.router)
app.include_router(alerts.router)
app.include_router(admin.router)


@app.get("/", tags=["Root"])
async def root():
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
    }
