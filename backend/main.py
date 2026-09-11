import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.database import get_db, engine, Base
import backend.models as models
from backend.routes.batches import router as batches_router
from backend.routes.reconciliation import router as reconciliation_router
from backend.routes.reports import router as reports_router
from backend.logging_config import setup_logging
from backend.config import ENVIRONMENT

# Initialize structured logging
logger = setup_logging(environment=ENVIRONMENT)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Attempt DB table creation on startup
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database schema initialized successfully.")
    except Exception as e:
        logger.warning(f"Notice: Could not automatically create tables at startup: {e}")
    yield
    logger.info("Application shutdown completed.")

app = FastAPI(
    title="Recon.ai API",
    description="Multi-Source Settlement Reconciler for Razorpay Merchants",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for React Frontend
_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Routers
app.include_router(batches_router)
app.include_router(reconciliation_router)
app.include_router(reports_router)

@app.get("/health", tags=["Health"])
def health_check(db: Session = Depends(get_db)):
    """Health check endpoint to verify backend service and DB connection."""
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"
        logger.error(f"Health check DB connection failed: {e}")
    
    return {
        "status": "ok",
        "app": "Multi-Source Settlement Reconciler (Recon.ai)",
        "database": db_status
    }

@app.get("/", tags=["Root"])
def root():
    return {
        "message": "Welcome to Recon.ai API. Visit /docs for OpenAPI documentation."
    }
