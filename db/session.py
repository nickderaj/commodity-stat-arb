"""SQLAlchemy engine and session factory.

Call get_session() to obtain a new Session. Always close the session in a finally block.
The engine is a module-level singleton created on first use.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

_engine: Engine | None = None
_SessionLocal = None


def get_database_url() -> str:
    """Build Postgres connection URL from environment variables."""
    user = os.environ["POSTGRES_USER"]
    password = os.environ["POSTGRES_PASSWORD"]
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ["POSTGRES_DB"]
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


def get_engine() -> Engine:
    """Return the module-level SQLAlchemy engine, creating it on first call."""
    global _engine
    if _engine is None:
        _engine = create_engine(get_database_url(), pool_pre_ping=True, hide_parameters=True)
    return _engine


def get_session() -> Session:
    """Return a new SQLAlchemy Session. Caller is responsible for closing it."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionLocal()


# Convenience alias for Alembic env.py
engine = None  # do not use at module level; call get_engine() instead
