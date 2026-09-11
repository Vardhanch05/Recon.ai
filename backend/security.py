import os
from typing import Optional
from fastapi import Header, HTTPException, status
from backend.config import API_KEY, REQUIRE_API_KEY

def verify_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> Optional[str]:
    """
    Validates API key for protected routes.
    If REQUIRE_API_KEY is enabled (default in production), missing or invalid keys fail closed.
    In development without REQUIRE_API_KEY or configured API_KEY, requests pass through.
    """
    configured_key = API_KEY.strip() if API_KEY else ""
    
    if REQUIRE_API_KEY:
        if not configured_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server configuration error: API key authentication is required but API_KEY is not configured."
            )
        if not x_api_key or x_api_key.strip() != configured_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key in X-API-Key header."
            )
        return x_api_key

    # If key is set in dev mode, validate it
    if configured_key:
        if not x_api_key or x_api_key.strip() != configured_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key in X-API-Key header."
            )
        return x_api_key

    return x_api_key
