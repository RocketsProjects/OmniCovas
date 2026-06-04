"""
omnicovas.db.engine

Async SQLAlchemy engine for the OmniCOVAS session database.

Law 6 (Performance Priority):
    All DB operations are async via aiosqlite. Zero blocking I/O.

Law 8 (Sovereignty & Transparency):
    Database file lives in %APPDATA%\\OmniCOVAS\\ — the commander owns it.
    Plain SQLite — inspectable, exportable, deletable at any time.

See: Phase 1 Development Guide Week 3, Part B
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from omnicovas.db.models import Base

logger = logging.getLogger(__name__)

# Database lives in AppData so it is per-user and survives app upgrades
APPDATA_DIR = Path(os.path.expandvars(r"%APPDATA%\OmniCOVAS"))
SESSION_DB_PATH = APPDATA_DIR / "omnicovas_session.db"


def build_database_url(db_path: Path) -> str:
    """
    Build the SQLAlchemy async URL for a SQLite database.

    Args:
        db_path: Absolute path to the .db file

    Returns:
        SQLAlchemy URL string suitable for create_async_engine
    """
    return f"sqlite+aiosqlite:///{db_path}"


async def init_database(db_path: Path | None = None) -> AsyncEngine:
    """
    Create the database directory, file, and schema if they do not exist.

    Args:
        db_path: Optional override for the database file path (for tests)

    Returns:
        Configured AsyncEngine ready for use by a session factory.
    """
    target_path = db_path or SESSION_DB_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)

    url = build_database_url(target_path)
    logger.info("Initializing session database at: %s", target_path)

    engine = create_async_engine(url, echo=False, future=True)

    # Create tables if they don't exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Session database ready.")
    return engine


def make_session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """
    Create a session factory bound to the given engine.

    Args:
        engine: An AsyncEngine from init_database

    Returns:
        async_sessionmaker that callers use with 'async with' to get sessions.
    """
    return async_sessionmaker(engine, expire_on_commit=False)
