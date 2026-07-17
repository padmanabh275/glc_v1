"""Shared FastAPI dependencies for authenticated data-plane routes."""

from __future__ import annotations

from fastapi import Header, HTTPException, Request

from glc.security.auth import client_ip, require_install_token
from glc.security.data_plane_limits import get_data_plane_limiter


async def require_data_plane(
    request: Request,
    authorization: str | None = Header(default=None),
) -> str:
    """Install token + per-IP/token rate limit + daily budget."""
    token = require_install_token(authorization)
    key = f"{client_ip(request)}:{token[:12]}"
    ok, why = get_data_plane_limiter().check(key)
    if not ok:
        raise HTTPException(429, why)
    return token
