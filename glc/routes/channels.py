"""WS /v1/channels/{name} — adapter control plane.

Adapters connect over WebSocket and exchange JSON-serialised
ChannelMessage and ChannelReply envelopes. Auth uses Authorization:
Bearer <install_token> or a short-lived ticket from /v1/control/ws-ticket
(passed as Sec-WebSocket-Protocol: glc.ticket.<ticket> for browsers).
Durable ?token= query auth is rejected (C3).

Inbound envelopes must have env.channel == path {name} (C2).
"""

from __future__ import annotations

import hmac
import json
import os

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from glc.audit import append as audit_append
from glc.channels import registry
from glc.channels.envelope import ChannelMessage, ChannelReply
from glc.channels.registry import discover
from glc.config import get_or_create_install_token, load_channels, save_channels
from glc.security.allowlists import allowed
from glc.security.auth import require_install_token
from glc.security.deps import require_data_plane
from glc.security.harden import maybe_commit_volume
from glc.security.pairing import get_pairing_store
from glc.security.rate_limits import get_rate_limiter
from glc.security.ws_tickets import consume_ticket

router = APIRouter()


class ChannelEnabledRequest(BaseModel):
    enabled: bool


def _ws_presented_token(websocket: WebSocket, token: str | None) -> str | None:
    header_auth = websocket.headers.get("authorization") or websocket.headers.get("Authorization")
    if header_auth and header_auth.startswith("Bearer "):
        return header_auth.removeprefix("Bearer ").strip()
    # Browser-friendly: Sec-WebSocket-Protocol: glc.bearer.<token> or glc.ticket.<ticket>
    proto = websocket.headers.get("sec-websocket-protocol") or ""
    for part in proto.split(","):
        part = part.strip()
        if part.startswith("glc.bearer."):
            return part.removeprefix("glc.bearer.")
        if part.startswith("glc.ticket."):
            return part.removeprefix("glc.ticket.")
    # C3: durable ?token= is no longer accepted
    if token:
        return None
    return None


def _ws_auth_ok(presented: str | None) -> bool:
    if not presented:
        return False
    expected = get_or_create_install_token()
    if presented == expected:
        return True
    return consume_ticket(presented)


@router.get("/v1/channels/catalogue")
async def channels_catalogue(_: str = Depends(require_data_plane)):
    """Read-only list of discovered channel adapters for the dashboard."""
    cfg = load_channels().get("channels") or {}
    adapters = discover()
    return {
        "channels": [
            {
                "name": name,
                "enabled": bool((cfg.get(name) or {}).get("enabled", True)),
                "adapter": f"{cls.__module__}.{cls.__name__}",
            }
            for name, cls in sorted(adapters.items())
        ]
    }


@router.patch("/v1/channels/{name}/enabled")
async def set_channel_enabled(
    name: str,
    req: ChannelEnabledRequest,
    authorization: str | None = Header(default=None),
):
    """Toggle a channel adapter on/off in ~/.glc/channels.yaml."""
    require_install_token(authorization)
    if name not in discover():
        raise HTTPException(404, f"unknown channel {name!r}")
    cfg = load_channels()
    channels = cfg.setdefault("channels", {})
    entry = channels.setdefault(name, {})
    entry["enabled"] = req.enabled
    save_channels(cfg)
    maybe_commit_volume()
    return {"name": name, "enabled": req.enabled}


@router.websocket("/v1/channels/{name}")
async def channel_ws(websocket: WebSocket, name: str, token: str | None = Query(default=None)):
    presented = _ws_presented_token(websocket, token)
    if not _ws_auth_ok(presented):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Echo chosen subprotocol if client offered one
    proto = websocket.headers.get("sec-websocket-protocol")
    if proto:
        chosen = proto.split(",")[0].strip()
        await websocket.accept(subprotocol=chosen)
    else:
        await websocket.accept()
    state = websocket.app.state
    registered = list(getattr(state, "registered_channels", []))
    if name not in registered:
        registered.append(name)
        state.registered_channels = registered

    limiter = get_rate_limiter()
    pairings = get_pairing_store()
    owners = [p.channel_user_id for p in pairings.owners(channel=name)]

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
                env = ChannelMessage.model_validate(payload)
            except Exception as e:
                await websocket.send_text(json.dumps({"error": f"invalid envelope: {e}"}))
                continue

            # C2 — reject cross-channel spoofing
            if env.channel != name:
                await websocket.send_text(
                    json.dumps({"error": f"channel mismatch: envelope {env.channel!r} != path {name!r}"})
                )
                continue

            ok, why = allowed(
                env.channel,
                env.channel_user_id,
                owner_ids=owners,
                is_public_channel=bool(env.metadata.get("is_public_channel", False)),
                was_mentioned=bool(env.metadata.get("was_mentioned", False)),
            )
            if not ok:
                audit_append(
                    channel=env.channel,
                    channel_user_id=env.channel_user_id,
                    trust_level=env.trust_level,
                    event_type="allowlist_drop",
                    result={"reason": why},
                )
                await websocket.send_text(json.dumps({"error": f"dropped: {why}"}))
                continue

            ok, why = limiter.check_message(env.channel, env.channel_user_id)
            if not ok:
                audit_append(
                    channel=env.channel,
                    channel_user_id=env.channel_user_id,
                    trust_level=env.trust_level,
                    event_type="rate_limit",
                    result={"reason": why},
                )
                await websocket.send_text(json.dumps({"status": 429, "error": why}))
                continue

            audit_append(
                channel=env.channel,
                channel_user_id=env.channel_user_id,
                trust_level=env.trust_level,
                event_type="inbound_message",
                params={"text": env.text, "thread_id": env.thread_id},
            )

            reply = ChannelReply(
                channel=env.channel,
                channel_user_id=env.channel_user_id,
                text=f"[glc echo] {env.text or ''}",
                thread_id=env.thread_id,
            )
            await websocket.send_text(reply.model_dump_json())
    except WebSocketDisconnect:
        return


@router.get("/v1/channels/{name}/webhook")
async def channel_webhook_verify(name: str, request: Request):
    params = dict(request.query_params)
    mode = params.get("hub.mode", "")
    token = params.get("hub.verify_token", "")
    challenge = params.get("hub.challenge", "")
    expected = os.environ.get(f"{name.upper()}_VERIFY_TOKEN", "")
    if mode == "subscribe" and hmac.compare_digest(token, expected):
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=403)


@router.post("/v1/channels/{name}/webhook")
async def channel_webhook(name: str, request: Request):
    try:
        adapter = registry.instantiate(name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown channel: {name}") from None

    raw = {
        "raw_body": await request.body(),
        "headers": dict(request.headers),
    }
    msg = await adapter.on_message(raw)
    if msg is None:
        return {"status": "ok"}

    if msg.channel != name:
        raise HTTPException(400, f"channel mismatch: envelope {msg.channel!r} != path {name!r}")

    limiter = get_rate_limiter()
    pairings = get_pairing_store()
    owners = [p.channel_user_id for p in pairings.owners(channel=name)]

    ok, why = allowed(
        msg.channel,
        msg.channel_user_id,
        owner_ids=owners,
        is_public_channel=bool(msg.metadata.get("is_public_channel", False)),
        was_mentioned=bool(msg.metadata.get("was_mentioned", False)),
    )
    if not ok:
        audit_append(
            channel=msg.channel,
            channel_user_id=msg.channel_user_id,
            trust_level=msg.trust_level,
            event_type="allowlist_drop",
            result={"reason": why},
        )
        return {"status": "ok"}

    ok, why = limiter.check_message(msg.channel, msg.channel_user_id)
    if not ok:
        audit_append(
            channel=msg.channel,
            channel_user_id=msg.channel_user_id,
            trust_level=msg.trust_level,
            event_type="rate_limit",
            result={"reason": why},
        )
        return JSONResponse(status_code=429, content={"error": why})

    audit_append(
        channel=msg.channel,
        channel_user_id=msg.channel_user_id,
        trust_level=msg.trust_level,
        event_type="inbound_message",
        params={"text": msg.text, "thread_id": msg.thread_id, "provider": msg.metadata.get("provider")},
    )

    reply = ChannelReply(
        channel=msg.channel,
        channel_user_id=msg.channel_user_id,
        text=f"[glc echo] {msg.text or ''}",
        thread_id=msg.thread_id,
    )
    await adapter.send(reply)
    return {"status": "ok"}
