import os
from typing import Optional
from fastapi import Header, HTTPException, status
from backend.config import API_KEY

def verify_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> Optional[str]:
    """
    Validates API key for protected routes if API_KEY is configured.
    If API_KEY is not set (e.g., local development without key configured),
    requests are permitted.
    """
    configured_key = API_KEY.strip() if API_KEY else ""
    if not configured_key:
        return x_api_key

    if not x_api_key or x_api_key.strip() != configured_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key in X-API-Key header."
        )
    return x_api_key
