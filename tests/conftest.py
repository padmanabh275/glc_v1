"""Shared fixtures.

Each test session gets a fresh isolated config/db dir so user state at
~/.glc/ is never touched. Per-test, the audit / pairing / gateway DBs
are rolled fresh.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_glc_state(monkeypatch, tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("GLC_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("GLC_AUDIT_DB", str(tmp_path / "audit.sqlite"))
    monkeypatch.setenv("GLC_PAIRING_DB", str(tmp_path / "pairings.sqlite"))
    monkeypatch.setenv("GLC_GATEWAY_DB", str(tmp_path / "gateway.sqlite"))
    # Tests need force_pair_owner; keep harden off for suite unless a test enables it.
    monkeypatch.setenv("GLC_ALLOW_FORCE_PAIR", "1")
    monkeypatch.delenv("GLC_HARDEN", raising=False)
    monkeypatch.delenv("GLC_DISABLE_DOCS", raising=False)

    # Reset singletons that cache config-dir at first access.
    import glc.config as _cfg

    _cfg.CONFIG_DIR = cfg
    import glc.security.pairing as _p

    _p._singleton = None
    import glc.security.rate_limits as _r

    _r._limiter = None
    import glc.security.data_plane_limits as _d

    _d._limiter = None
    import glc.policy.engine as _e

    _e._engine = None
    _e._frozen = False
    import glc.audit.store as _a

    _a._singleton = None
    import glc.security.harden as _h

    _h._APPLIED = False
    yield


@pytest.fixture
def app_client():
    """TestClient pointed at a freshly-booted glc.main:app."""
    from fastapi.testclient import TestClient

    import glc.main as m

    with TestClient(m.app) as c:
        yield c


@pytest.fixture
def install_token(app_client):
    """Returns the per-installation token created during boot."""
    from glc.config import install_token_path

    return install_token_path().read_text().strip()


@pytest.fixture
def auth_headers(install_token):
    return {"Authorization": f"Bearer {install_token}"}
