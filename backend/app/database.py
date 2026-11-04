"""Database engine, session factory and FastAPI dependency.

Design choice: **synchronous** SQLAlchemy.
FastAPI can run sync endpoints in a threadpool, and Celery tasks are sync
anyway. Using the sync API means one driver, one mental model, and no
"greenlet_spawn has not been called" surprises mid-hackathon.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base: all ORM models inherit from this."""


def _engine_options(url: str) -> dict:
    options: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        # SQLite needs this when the same connection is used from the
        # threadpool that FastAPI runs sync endpoints in.
        options["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            # One shared in-memory DB for the whole test session.
            options["poolclass"] = StaticPool
    else:
        # Recycle before managed Postgres/Redis providers kill idle conns.
        options["pool_recycle"] = 1800
    return options


engine: Engine = create_engine(settings.database_url, **_engine_options(settings.database_url))

if settings.database_url.startswith("sqlite"):
    # SQLite ignores foreign keys unless asked. Without this, ON DELETE CASCADE
    # silently does nothing when using the no-Docker fallback.
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,  # objects stay usable after commit
    class_=Session,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Transactional scope for workers/scripts.

    Commits on success, rolls back on any exception, always closes:

        with session_scope() as db:
            db.add(obj)
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
