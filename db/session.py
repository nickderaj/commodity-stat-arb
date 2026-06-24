import os
from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

load_dotenv()

_engine: Engine | None = None
_SessionLocal = None


def get_database_url() -> str:
    user = os.environ["POSTGRES_USER"]
    password = os.environ["POSTGRES_PASSWORD"]
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ["POSTGRES_DB"]
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(get_database_url(), pool_pre_ping=True, hide_parameters=True)
    return _engine


def get_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionLocal()


# Convenience alias for Alembic env.py
engine = None  # do not use at module level; call get_engine() instead
