"""Short-lived WS tickets so browsers need not put the install token in ?token=."""

from __future__ import annotations

import secrets
import threading
import time

_TICKETS: dict[str, float] = {}
_LOCK = threading.Lock()
_TTL_S = 60.0


def issue_ticket() -> tuple[str, float]:
    tok = secrets.token_urlsafe(24)
    expires = time.time() + _TTL_S
    with _LOCK:
        _TICKETS[tok] = expires
        _gc()
    return tok, expires


def consume_ticket(tok: str) -> bool:
    now = time.time()
    with _LOCK:
        _gc()
        exp = _TICKETS.pop(tok, None)
    return exp is not None and exp >= now


def _gc() -> None:
    now = time.time()
    dead = [k for k, exp in _TICKETS.items() if exp < now]
    for k in dead:
        _TICKETS.pop(k, None)
