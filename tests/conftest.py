"""
Shared pytest fixtures.

Design: tests in this suite must NEVER hit:
  * the real OpenAI API
  * the production Postgres
  * the real Redis broker
  * any external HTTP endpoint

We pin a minimal set of env vars below before app modules are imported,
so :func:`app.config.get_settings` produces a sandbox-friendly Settings
instance even on a developer laptop with no `.env`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Repo root must be on sys.path so `import app.…` resolves when pytest
# is invoked from the project root.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Sandbox env BEFORE app.config is imported anywhere.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("LOG_FORMAT", "console")
os.environ.setdefault("LOG_LEVEL", "WARNING")
# A throw-away SQLite path — most unit tests don't touch the engine,
# but a few (database tests) need *some* valid URL.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("OPENAI_API_KEY", "")  # explicitly empty — guards live calls

import pytest


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Clear the lru_cache on get_settings so per-test env mutation works."""
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
