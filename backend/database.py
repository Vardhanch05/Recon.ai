import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

try:
    from backend.config import DATABASE_URL
except ImportError:
    from config import DATABASE_URL

# Base class which all 7 models in models.py inherit from
Base = declarative_base()

def create_resilient_engine(url: str):
    """
    Creates a database engine. If PostgreSQL connection is refused (server not running),
    it automatically falls back to a zero-configuration local SQLite database (recon_ai.db)
    so the entire UI and backend can run seamlessly.
    """
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False}, echo=False)
    
    try:
        eng = create_engine(url, echo=False)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return eng
    except Exception as e:
        print(f"\n[NOTICE] PostgreSQL at {url} is not running ({e}).")
        print("[NOTICE] Automatically switching to local SQLite database (sqlite:///./recon_ai.db) for zero-setup execution.\n")
        fallback_url = "sqlite:///./recon_ai.db"
        return create_engine(fallback_url, connect_args={"check_same_thread": False}, echo=False)

# Initialize the SQLAlchemy Engine
engine = create_resilient_engine(DATABASE_URL)

# SessionLocal factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Auto-create all tables on engine initialization
try:
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"Table initialization notice: {e}")

def get_db():
    """
    Dependency generator providing an isolated session for each API request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()