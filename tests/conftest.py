import pytest
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure in-memory database for tests
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from backend.database import Base, get_db
from backend.main import app
import backend.models as models
import backend.database as db_mod
import backend.routes.reconciliation as recon_route

# Test SQLite Engine in memory with static pool to share connection across threads
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(autouse=True)
def clean_test_db():
    """Provides complete test isolation by recreating the schema for every test."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)

@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(autouse=True)
def override_get_db(monkeypatch):
    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()
    
    app.dependency_overrides[get_db] = _override_get_db
    monkeypatch.setattr(db_mod, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(recon_route, "SessionLocal", TestingSessionLocal)
    yield
    app.dependency_overrides.clear()
