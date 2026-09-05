from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.database import get_db, engine, Base
import backend.models as models

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Attempt DB table creation on startup
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        print(f"Notice: Could not automatically create tables at startup: {e}")
    yield

app = FastAPI(
    title="Recon.ai API",
    description="Multi-Source Settlement Reconciler for Razorpay Merchants",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for React Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health", tags=["Health"])
def health_check(db: Session = Depends(get_db)):
    """Health check endpoint to verify backend service and DB connection."""
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
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
