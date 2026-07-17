"""Process hardening for Modal / GLC_HARDEN=1 (B1, B6, B8 and helpers)."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import Any

_APPLIED = False

_SECRET_SUBSTRINGS = (
    "API_KEY",
    "OPENAI",
    "ANTHROPIC",
    "GEMINI",
    "GROQ",
    "ELEVENLABS",
    "CARTESIA",
    "TWILIO_AUTH",
    "WHATSAPP_TOKEN",
    "WHATSAPP_APP_SECRET",
)

# Modules allowed to use subprocess under harden (voice providers).
_SUBPROCESS_ALLOW = (
    "glc.voice.",
    "uvicorn.",
    "asyncio.",
    "concurrent.",
    "multiprocessing.",
)


def harden_enabled() -> bool:
    return os.getenv("GLC_HARDEN", "").strip().lower() in ("1", "true", "yes")


def scrub_provider_secrets_from_environ() -> list[str]:
    """Remove provider credentials from os.environ (A4/B1). Returns removed keys."""
    removed: list[str] = []
    for k in list(os.environ.keys()):
        ku = k.upper()
        if any(s in ku for s in _SECRET_SUBSTRINGS):
            # Keep GLC_* control flags
            if ku.startswith("GLC_"):
                continue
            os.environ.pop(k, None)
            removed.append(k)
    return removed


def apply_process_hardening() -> None:
    """Idempotent process-level guards for B6/B8 and env scrub."""
    global _APPLIED
    if _APPLIED:
        return
    if not harden_enabled():
        return
    scrub_provider_secrets_from_environ()
    _install_os_kill_guard()
    _install_subprocess_guard()
    _APPLIED = True


def _install_os_kill_guard() -> None:
    import os as _os
    import signal

    real_kill = _os.kill

    def guarded_kill(pid: int, sig: int) -> None:  # type: ignore[no-untyped-def]
        # Allow existence probe
        if sig == 0:
            return real_kill(pid, sig)
        # Allow self-SIGTERM only from control.kill path via env latch
        if os.getenv("GLC_ALLOW_SELF_KILL", "") == "1" and pid == _os.getpid() and sig in (
            signal.SIGTERM,
            getattr(signal, "CTRL_C_EVENT", signal.SIGTERM),
        ):
            return real_kill(pid, sig)
        raise PermissionError("os.kill blocked under GLC_HARDEN (B6)")

    _os.kill = guarded_kill  # type: ignore[assignment]


def _caller_allowed_for_subprocess() -> bool:
    frame = sys._getframe(2)  # noqa: SLF001
    while frame:
        mod = frame.f_globals.get("__name__", "") or ""
        if any(mod.startswith(p) for p in _SUBPROCESS_ALLOW):
            return True
        # allow harden / repro / tests
        if mod.startswith("glc.security.harden") or mod.startswith("tests.") or mod.startswith("pytest"):
            return True
        frame = frame.f_back  # type: ignore[assignment]
    return False


def _install_subprocess_guard() -> None:
    import subprocess as _sp

    real_run = _sp.run
    real_popen = _sp.Popen

    def guarded_run(*args: Any, **kwargs: Any) -> Any:
        if not _caller_allowed_for_subprocess():
            raise PermissionError("subprocess.run blocked under GLC_HARDEN (B8)")
        return real_run(*args, **kwargs)

    class GuardedPopen(real_popen):  # type: ignore[valid-type,misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            if not _caller_allowed_for_subprocess():
                raise PermissionError("subprocess.Popen blocked under GLC_HARDEN (B8)")
            super().__init__(*args, **kwargs)

    _sp.run = guarded_run  # type: ignore[assignment]
    _sp.Popen = GuardedPopen  # type: ignore[misc,assignment]


def volume_commit_hook() -> Callable[[], None] | None:
    """Optional Modal Volume.commit callback set by modal_app."""
    return getattr(sys.modules.get("glc.security.harden"), "_VOLUME_COMMIT", None)


_VOLUME_COMMIT: Callable[[], None] | None = None


def set_volume_commit(fn: Callable[[], None] | None) -> None:
    global _VOLUME_COMMIT
    _VOLUME_COMMIT = fn


def maybe_commit_volume() -> None:
    if _VOLUME_COMMIT is not None:
        try:
            _VOLUME_COMMIT()
        except Exception:
            pass
