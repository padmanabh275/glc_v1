"""In-process leak harness for B1–B8 (Session 12 Section 7).

Run inside a hardened process (GLC_HARDEN=1). Each check prints PASS/FAIL.
Exit code 0 only if all expected blocks succeed.
"""

from __future__ import annotations

import os
import sqlite3
import sys

os.environ["GLC_HARDEN"] = "1"
os.environ["GLC_ALLOW_FORCE_PAIR"] = "0"


def main() -> int:
    fails = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal fails
        status = "PASS" if ok else "FAIL"
        if not ok:
            fails += 1
        print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))

    from glc.security import harden as harden_mod

    # Reset so apply runs fresh
    harden_mod._APPLIED = False  # noqa: SLF001
    os.environ["OPENAI_API_KEY"] = "sk-test-should-be-scrubbed"
    harden_mod.apply_process_hardening()
    keys = [k for k in os.environ if any(s in k.upper() for s in ("API_KEY", "OPENAI", "GEMINI", "ANTHROPIC"))]
    check("B1 env scrub", "OPENAI_API_KEY" not in os.environ, f"leftover={keys[:5]}")

    from glc.audit import store as audit_store

    audit_store.init_store()
    blocked = False
    try:
        with audit_store._conn() as c:  # noqa: SLF001
            c.execute("DELETE FROM audit_log")
    except sqlite3.DatabaseError:
        blocked = True
    except Exception as e:
        blocked = "denied" in str(e).lower() or "authorizer" in str(e).lower()
    check("B2 audit DELETE blocked", blocked)

    from glc.security.pairing import get_pairing_store

    raised = False
    try:
        get_pairing_store().force_pair_owner("signal", "+10000000000")
    except PermissionError:
        raised = True
    check("B3 force_pair_owner gated", raised)

    from glc.security.auth import token_readable_by_callers

    check("B4 token gated", not token_readable_by_callers())

    from glc.policy import engine as pe

    pe._frozen = False  # noqa: SLF001
    pe.get_engine()
    pe.freeze_engine()
    frozen = False
    try:
        pe.reload_engine()
    except RuntimeError:
        frozen = True
    check("B5 policy freeze", frozen)

    kill_blocked = False
    try:
        import signal

        os.kill(os.getpid(), signal.SIGTERM)
    except PermissionError:
        kill_blocked = True
    check("B6 os.kill blocked", kill_blocked)

    from glc import db

    poisoned = False
    try:
        db.log_call(provider="evil", model="x", status="ok")
    except PermissionError:
        poisoned = True
    check("B7 log_call gated", poisoned)

    import subprocess

    sub_blocked = False
    try:
        subprocess.run([sys.executable, "-c", "print(1)"], check=False, capture_output=True)
    except PermissionError:
        sub_blocked = True
    check("B8 subprocess blocked", sub_blocked)

    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
