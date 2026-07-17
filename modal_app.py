"""
Modal deployment wrapper for hardened glc_v1 (Session 12 Part 1).

- Reproducible image from uv.lock (A5)
- Single ASGI container writer for SQLite audit (A6)
- Provider secrets on a separate llm_egress Function; ASGI scrubs env (A3/A4/B1)
- GLC_HARDEN / GLC_DISABLE_DOCS enabled in the image

Deploy:  uv run modal deploy modal_app.py
"""

from __future__ import annotations

from pathlib import Path

import modal

app = modal.App("glc-v1-gateway")

ROOT = Path(__file__).parent
LOCAL_GLC = ROOT / "glc"
LOCAL_LOCK = ROOT / "uv.lock"
LOCAL_PYPROJECT = ROOT / "pyproject.toml"

# Pin base by digest when available; fallback tag documented for A5.
# Update digest periodically after verifying: docker pull python:3.11-slim-bookworm
_BASE = "python:3.11-slim-bookworm"

image = (
    modal.Image.from_registry(_BASE)
    .apt_install("ca-certificates")
    .run_commands(
        "pip install --no-cache-dir uv==0.7.12",
    )
    .env(
        {
            "GLC_CONFIG_DIR": "/data/glc",
            "GLC_HARDEN": "1",
            "GLC_DISABLE_DOCS": "1",
            "GLC_LLM_EGRESS": "modal",
            "PYTHONPATH": "/root",
        }
    )
    .add_local_file(str(LOCAL_PYPROJECT), remote_path="/root/pyproject.toml")
    .add_local_file(str(LOCAL_LOCK), remote_path="/root/uv.lock")
    .add_local_dir(str(LOCAL_GLC), remote_path="/root/glc")
    .run_commands(
        "cd /root && uv sync --frozen --no-dev --link-mode=copy",
    )
)

data_volume = modal.Volume.from_name("glc-data", create_if_missing=True)
llm_secret = modal.Secret.from_name("glc-llm-keys")

# Provider egress allowlist (A3) — mock-friendly public API hosts only.
_EGRESS_ALLOW = [
    "generativelanguage.googleapis.com",
    "api.openai.com",
    "api.groq.com",
    "api.cerebras.ai",
    "integrate.api.nvidia.com",
    "openrouter.ai",
    "api.github.com",
    "models.github.ai",
    "api.elevenlabs.io",
    "api.cartesia.ai",
]


@app.function(
    image=image,
    secrets=[llm_secret],
    # Modal domain allowlist — if unsupported in this SDK version, still
    # keep secrets off the ASGI function (A4).
    timeout=120,
)
def llm_egress(method: str, url: str, headers: dict, body: bytes | None = None) -> dict:
    """Outbound HTTP for providers — secrets live only here."""
    import httpx

    host = httpx.URL(url).host or ""
    if not any(host == d or host.endswith("." + d) for d in _EGRESS_ALLOW):
        return {"error": f"egress denied for host {host!r}", "status": 403, "body": b""}
    with httpx.Client(timeout=60.0, follow_redirects=False) as client:
        r = client.request(method, url, headers=headers, content=body)
        return {"status": r.status_code, "headers": dict(r.headers), "body": r.content}


@app.function(
    image=image,
    volumes={"/data": data_volume},
    # No llm_secret on ASGI — A4/B1
    min_containers=0,
    max_containers=1,  # A6 single SQLite writer
)
@modal.asgi_app()
def fastapi_app():
    import os

    os.makedirs("/data/glc", exist_ok=True)
    os.environ["GLC_HARDEN"] = "1"
    os.environ["GLC_DISABLE_DOCS"] = "1"

    from glc.security.harden import apply_process_hardening, set_volume_commit

    def _commit() -> None:
        data_volume.commit()

    set_volume_commit(_commit)
    apply_process_hardening()

    from glc.main import app as web

    return web
