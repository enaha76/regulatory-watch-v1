"""Critical safety test: schema autocreate must NOT run unless opted in.

Regression test for the bug we hit on 2026-04 where
`SQLModel.metadata.create_all()` raced an Alembic migration and produced
a `DuplicateTable` error.
"""

from __future__ import annotations

import pytest


def test_create_db_and_tables_refuses_when_dev_flag_off(monkeypatch):
    monkeypatch.setenv("DEV_AUTOCREATE_TABLES", "false")
    from app.config import get_settings
    get_settings.cache_clear()

    from app import database
    with pytest.raises(RuntimeError, match="DEV_AUTOCREATE_TABLES is false"):
        database.create_db_and_tables()


def test_create_db_and_tables_refuses_in_default_settings(monkeypatch):
    # Default config has DEV_AUTOCREATE_TABLES=False — must refuse.
    monkeypatch.delenv("DEV_AUTOCREATE_TABLES", raising=False)
    from app.config import get_settings
    get_settings.cache_clear()

    from app import database
    with pytest.raises(RuntimeError):
        database.create_db_and_tables()
