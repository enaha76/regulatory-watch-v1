"""
Database engine and session management.

Pool sizing
-----------
SQLAlchemy's defaults (pool_size=5, max_overflow=10) are too tight for
an environment running an API + multiple Celery workers + occasional
CLI scripts concurrently. We size explicitly via ``app.config.Settings``
so they can be tuned per-environment without code changes.

Schema management
-----------------
Alembic is the **only** writer of schema in production. The
``create_db_and_tables()`` helper is gated behind
``DEV_AUTOCREATE_TABLES`` and intentionally raises in non-dev
environments to prevent the kind of race we hit on 2026-04 where
``SQLModel.metadata.create_all()`` raced with an Alembic migration
and produced ``DuplicateTable``.
"""

from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings


def get_engine():
    """Create the SQLAlchemy engine, sized for multi-process workloads."""
    settings = get_settings()
    return create_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_timeout=settings.DB_POOL_TIMEOUT,
    )


engine = get_engine()


def create_db_and_tables() -> None:
    """Create all SQLModel-declared tables.

    Refuses to run unless ``DEV_AUTOCREATE_TABLES=true``. Production
    schema is owned by Alembic; using ``metadata.create_all()`` there
    races migrations and silently drifts from the version table.
    """
    settings = get_settings()
    if not settings.DEV_AUTOCREATE_TABLES:
        raise RuntimeError(
            "create_db_and_tables() refused: DEV_AUTOCREATE_TABLES is false. "
            "Use `alembic upgrade head` to apply schema changes."
        )
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a DB session per request."""
    with Session(engine) as session:
        yield session
