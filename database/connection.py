"""
database/connection.py
AlloyDB connection pool using pg8000 (native Python, no libpq dependency).
Pattern: externalized config, stateless — safe for Cloud Run.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Generator

import pg8000.native
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

logger = logging.getLogger(__name__)

# ── Build connection URL from environment ────────────────────────────────────
def _get_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host     = os.getenv("ALLOYDB_HOST", "127.0.0.1")
    port     = os.getenv("ALLOYDB_PORT", "5432")
    db       = os.getenv("ALLOYDB_DB",   "postgres")
    user     = os.getenv("ALLOYDB_USER", "postgres")
    password = os.getenv("ALLOYDB_PASSWORD", "")
    return f"postgresql+pg8000://{user}:{password}@{host}:{port}/{db}"


# ── Engine (singleton per process — Cloud Run starts one process) ─────────────
_engine = None

def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            _get_db_url(),
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,       # detect stale connections
            pool_recycle=1800,        # recycle every 30 min
            echo=os.getenv("SQL_ECHO", "false").lower() == "true",
        )
        logger.info("AlloyDB engine initialised")
    return _engine


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=None)


def get_session() -> Session:
    """Return a new SQLAlchemy session bound to the AlloyDB engine."""
    session = SessionLocal(bind=get_engine())
    return session


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """Context-manager session with automatic commit/rollback."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_schema(sql_path: str = "database/schema.sql") -> None:
    """Apply schema SQL file (idempotent — uses IF NOT EXISTS everywhere)."""
    with open(sql_path) as f:
        ddl = f.read()
    with get_engine().connect() as conn:
        # Split on ";" and run each non-empty statement
        for stmt in ddl.split(";"):
            stmt = stmt.strip()
            if stmt and not stmt.startswith("--") and not stmt.startswith("/*"):
                conn.execute(text(stmt))
        conn.commit()
    logger.info("Schema applied from %s", sql_path)
