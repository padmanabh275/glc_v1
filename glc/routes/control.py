"""Out-of-band control plane: /v1/control/kill, /v1/control/pair,
/v1/control/pair/confirm, /v1/control/presence.

All endpoints require the installation token (Authorization: Bearer ...).
The kill endpoint binds 127.0.0.1 only; the host check is enforced here.
"""

from __future__ import annotations

import os
import signal
import threading
import time
from collections import deque

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from glc.security.auth import client_ip, require_install_token
from glc.security.pairing import CODE_TTL_SECONDS, get_pairing_store
from glc.security.ws_tickets import issue_ticket

router = APIRouter()

_pair_hits: dict[str, deque[float]] = {}
_pair_lock = threading.Lock()
_PAIR_RPM = int(os.getenv("GLC_PAIR_RPM", "10"))


def _check_pair_rate(key: str) -> None:
    now = time.time()
    with _pair_lock:
        dq = _pair_hits.setdefault(key, deque())
        while dq and dq[0] < now - 60:
            dq.popleft()
        if len(dq) >= _PAIR_RPM:
            raise HTTPException(429, f"pairing rate limit {_PAIR_RPM}/min exceeded")
        dq.append(now)


class PairRequest(BaseModel):
    channel: str
    channel_user_id: str
    user_handle: str = ""
    trust_level: str = "user_paired"


class PairResponse(BaseModel):
    code: str
    expires_at: float
    ttl_seconds: int


class PairConfirmRequest(BaseModel):
    code: str


class WsTicketResponse(BaseModel):
    ticket: str
    expires_at: float
    ttl_seconds: int = 60


@router.post("/v1/control/pair", response_model=PairResponse)
async def pair(req: PairRequest, request: Request, authorization: str | None = Header(default=None)):
    require_install_token(authorization)
    _check_pair_rate(f"issue:{client_ip(request)}")
    if req.trust_level not in ("user_paired", "owner_paired"):
        raise HTTPException(400, f"trust_level must be user_paired or owner_paired, got {req.trust_level!r}")
    code, expires_at = get_pairing_store().issue_code(
        req.channel,
        req.channel_user_id,
        req.user_handle,
        requested_trust_level=req.trust_level,
    )
    return PairResponse(code=code, expires_at=expires_at, ttl_seconds=CODE_TTL_SECONDS)


@router.post("/v1/control/pair/confirm")
async def pair_confirm(
    req: PairConfirmRequest, request: Request, authorization: str | None = Header(default=None)
):
    require_install_token(authorization)
    _check_pair_rate(f"confirm:{client_ip(request)}:{req.code}")
    rec = get_pairing_store().confirm_code(req.code)
    if rec is None:
        raise HTTPException(404, "code unknown or expired")
    return {
        "channel": rec.channel,
        "channel_user_id": rec.channel_user_id,
        "user_handle": rec.user_handle,
        "trust_level": rec.trust_level,
        "paired_at": rec.paired_at,
    }


@router.post("/v1/control/ws-ticket", response_model=WsTicketResponse)
async def ws_ticket(authorization: str | None = Header(default=None)):
    """Issue a short-lived ticket for WebSocket auth (C3 — no durable ?token=)."""
    require_install_token(authorization)
    ticket, expires_at = issue_ticket()
    return WsTicketResponse(ticket=ticket, expires_at=expires_at)


@router.get("/v1/control/presence")
async def presence(request: Request, authorization: str | None = Header(default=None)):
    require_install_token(authorization)
    state = request.app.state
    started = getattr(state, "started_at", time.time())
    pairings = get_pairing_store().all_pairings()
    return {
        "channels": getattr(state, "registered_channels", []),
        "paired_users": [
            {
                "channel": p.channel,
                "channel_user_id": p.channel_user_id,
                "user_handle": p.user_handle,
                "trust_level": p.trust_level,
            }
            for p in pairings
        ],
        "uptime_s": int(time.time() - started),
    }


@router.post("/v1/control/kill")
async def kill(request: Request, authorization: str | None = Header(default=None)):
    require_install_token(authorization)
    client_host = request.client.host if request.client else "unknown"
    if os.getenv("GLC_KILL_ALLOW_REMOTE") != "1" and client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(
            403,
            f"kill is restricted to loopback (got {client_host}). "
            "Set GLC_KILL_ALLOW_REMOTE=1 to override (not recommended).",
        )
    import asyncio

    async def _shoot() -> None:
        await asyncio.sleep(0.2)
        os.environ["GLC_ALLOW_SELF_KILL"] = "1"
        try:
            os.kill(os.getpid(), signal.SIGTERM)
        finally:
            os.environ.pop("GLC_ALLOW_SELF_KILL", None)

    asyncio.create_task(_shoot())
    return {"status": "terminating", "pid": os.getpid()}
