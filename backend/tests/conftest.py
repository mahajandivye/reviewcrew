"""Shared pytest fixtures.

The tests run against **SQLite in memory**, not PostgreSQL, so `pytest` needs
no Docker and no server: clone -> install -> `pytest`. The SQLAlchemy models and
queries used by the API are portable, so this catches real regressions.

Order matters: environment variables are set BEFORE importing app modules,
because `app.database` builds the engine at import time.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# --- test environment (must precede app imports) --------------------------- #
os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["GITHUB_WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["GITHUB_TOKEN"] = "ghp_test_token_not_real"
os.environ["OPENAI_API_KEY"] = ""  # never call the real API from tests
os.environ["POST_PR_COMMENTS"] = "false"  # never post to GitHub from tests
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402

get_settings.cache_clear()

from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_database():
    """Give every test a schema-clean database."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture()
def client():
    """TestClient runs the real ASGI app, including lifespan and CORS."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
