import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

try:
    from backend.config import DATABASE_URL
except ImportError:
    from config import DATABASE_URL

# Base class which all models in models.py inherit from
Base = declarative_base()


def create_db_engine(url: str):
    """
    Creates a SQLAlchemy engine from the configured DATABASE_URL.
    Supports both PostgreSQL (production) and SQLite (development/testing).

    NOTE: The silent PostgreSQL→SQLite auto-fallback has been removed (was C4).
    Configure DATABASE_URL explicitly in .env. If the DB is unreachable, the
    app will fail fast with a clear error rather than silently degrade.
    """
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not configured. Set it in your .env file.\n"
            "  PostgreSQL (recommended): postgresql://user:pass@host:5432/dbname\n"
            "  SQLite (development only): sqlite:///./recon_ai.db"
        )

    if url.startswith("sqlite"):
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            echo=False,
        )

    # PostgreSQL — pool_pre_ping ensures stale connections are detected
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        echo=False,
    )


# Initialize engine from configured URL (fails fast if misconfigured)
engine = create_db_engine(DATABASE_URL)

# SessionLocal factory — one session per request, closed in finally block
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# NOTE: Table creation is handled by the lifespan hook in main.py.
# create_all() is NOT called here at module import time (was H8 — race
# condition in multi-worker deployments). Use Alembic migrations in production.


def get_db():
    """
    Dependency generator providing an isolated session for each API request.
    Session is always closed in the finally block, even on exceptions.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()