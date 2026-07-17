"""SSRF-safe outbound image URL validation and fetch (C1)."""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

import httpx

# Default allowlist: common public object stores / CDNs used for vision demos.
_DEFAULT_SUFFIXES = (
    "googleapis.com",
    "googleusercontent.com",
    "gstatic.com",
    "cloudfront.net",
    "amazonaws.com",
    "azureedge.net",
    "github.com",
    "githubusercontent.com",
    "imgur.com",
    "wikimedia.org",
)


class UrlFetchError(ValueError):
    pass


def _allow_suffixes() -> tuple[str, ...]:
    raw = os.getenv("GLC_IMAGE_URL_ALLOW_SUFFIXES", "")
    if raw.strip():
        return tuple(s.strip().lower() for s in raw.split(",") if s.strip())
    return _DEFAULT_SUFFIXES


def _host_allowed(host: str) -> bool:
    host = host.lower().rstrip(".")
    for suf in _allow_suffixes():
        if host == suf or host.endswith("." + suf):
            return True
    return False


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve_and_check(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise UrlFetchError(f"dns failed for {host!r}") from e
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            raise UrlFetchError(f"blocked address {addr} for host {host!r}")


def host_on_allowlist(host: str) -> bool:
    return _host_allowed(host)


def assert_safe_image_url(url: str, *, resolve_dns: bool = True) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UrlFetchError("only http(s) image URLs allowed")
    host = parsed.hostname
    if not host:
        raise UrlFetchError("missing host")
    # Literal IPs in the URL
    try:
        ip = ipaddress.ip_address(host)
        if _is_blocked_ip(ip):
            raise UrlFetchError(f"blocked literal address {host}")
    except ValueError:
        pass
    if not _host_allowed(host):
        raise UrlFetchError(f"host {host!r} not on image URL allowlist")
    if resolve_dns:
        _resolve_and_check(host)


async def fetch_image_as_data_url(url: str, *, timeout: float = 15.0, max_bytes: int = 5_000_000) -> str:
    """Fetch an allowlisted image URL with redirect re-validation."""
    assert_safe_image_url(url)
    headers = {"User-Agent": "glc-v1-vision/1.0"}
    current = url
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, headers=headers) as client:
        for _ in range(5):
            assert_safe_image_url(current)
            r = await client.get(current)
            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("location")
                if not loc:
                    raise UrlFetchError("redirect without Location")
                current = str(httpx.URL(current).join(loc))
                continue
            r.raise_for_status()
            body = r.content
            if len(body) > max_bytes:
                raise UrlFetchError("image too large")
            ctype = (r.headers.get("content-type") or "application/octet-stream").split(";")[0].strip()
            if not ctype.startswith("image/") and ctype not in ("application/octet-stream",):
                # still allow if magic looks image-like; otherwise reject
                if not body[:3]:
                    raise UrlFetchError("empty body")
            import base64

            b64 = base64.b64encode(body).decode("ascii")
            return f"data:{ctype};base64,{b64}"
        raise UrlFetchError("too many redirects")
