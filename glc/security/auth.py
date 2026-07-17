"""Install-token auth for control plane and data plane."""

from __future__ import annotations

import os

from fastapi import Header, HTTPException, Request

from glc.config import get_or_create_install_token

# Callers outside glc.security.auth / glc.routes.control must not read the token
# file when hardening is on (B4).
_TOKEN_CALLER_OK = frozenset(
    {
        "glc.security.auth",
        "glc.routes.control",
        "glc.cli",
        "glc.main",
    }
)


def require_install_token(authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency: require Authorization: Bearer <install_token>."""
    expected = get_or_create_install_token()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token (Authorization: Bearer <install_token>)")
    presented = authorization.removeprefix("Bearer ").strip()
    if presented != expected:
        raise HTTPException(403, "install token mismatch")
    return presented


def require_install_token_value(authorization: str | None) -> str:
    """Non-dependency form for WebSocket / manual checks."""
    return require_install_token(authorization)


def token_readable_by_callers() -> bool:
    """B4: under GLC_HARDEN, adapters must not freely read the install token."""
    if os.getenv("GLC_HARDEN", "").strip().lower() not in ("1", "true", "yes"):
        return True
    return False


def client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
