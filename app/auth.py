from __future__ import annotations

import os

from fastapi import Header, HTTPException


def require_api_key(authorization: str | None = Header(default=None)) -> None:
    """Optionally require a Bearer token when API_KEY is configured."""
    expected = os.getenv("API_KEY", "").strip()
    if not expected:
        return

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization Bearer token")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Missing Authorization Bearer token")

    if token.strip() != expected:
        raise HTTPException(status_code=403, detail="Invalid API token")
