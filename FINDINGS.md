# Session 12 Part 1 — Findings

Hardened `glc_v1` against Section 6 (A/C) and Section 7 (B) findings.
Invariant map: Architecture moves 1–6 ([`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)),
plus **7 = append-only / single-writer audit integrity**, **8 = rate limits + hard budgets**.

Repro scripts: [`scripts/s12_repro/`](scripts/s12_repro/). Use **mock keys only**.
In-process B checks use `inprocess_b_leaks.py` (stands in for the lecture Section 2
two-file `gateway.py` + adapter harness — same leak surface, against this codebase).

| ID | Summary | Invariant | Status | Fix |
|----|---------|-----------|--------|-----|
| A1 | Public data plane, no auth | 4 | fixed | `require_data_plane` on chat/speak/transcribe |
| A2 | Info disclosure + Swagger | 4 | fixed | Auth on status/providers/…; `GLC_DISABLE_DOCS=1` |
| A3 | No egress wall | S12 env | fixed | `llm_egress` Modal Function + host allowlist |
| A4 / B1 | One Secret / env keys | S12 env | fixed | Secrets only on egress Fn; `scrub_provider_secrets` |
| A5 | Non-reproducible image | supply-chain | fixed | `uv.lock` + pinned base in `modal_app.py` |
| A6 | Audit SQLite + autoscale | 7 | fixed | `max_containers=1` + Volume.commit; DBs under `/data/glc` |
| B2 | Audit DELETE/DROP | 3, 6, 7 | fixed | SQLite authorizer (DELETE/DROP; UPDATE only on `audit_log`) |
| B3 | `force_pair_owner` | 3, 4 | fixed | Requires `GLC_ALLOW_FORCE_PAIR=1` when hardened |
| B4 | Install token readable | 4 | fixed | `token_readable_by_callers()` false under harden |
| B5 | Policy monkey-patch | 2 | fixed | `freeze_engine()`; reload only with `force=` |
| B6 | In-process `os.kill` | 4 | fixed | Guarded `os.kill` under harden |
| B7 | `log_call` poisoning | 6 | fixed | Caller allowlist under harden |
| B8 | subprocess | 1 | fixed | Guarded except voice allowlist |
| C1 | SSRF `/v1/vision` | 1 | fixed | `glc/security/url_fetch.py` |
| C2 | Envelope spoofing | 1 | fixed | `env.channel == name` on WS/webhook |
| C3 | WS `?token=` | 4 | fixed | Short-lived `/v1/control/ws-ticket` + subprotocol |
| C4 | Verbose upstream errors | 4 | fixed | Generic `upstream_error` to clients |
| C5 | No data-plane budgets | 8 | fixed | `DataPlaneLimiter` RPM + daily budget |
| C6 | Pairing brute force | 8 | fixed | Rate limit on pair/confirm |

## Commits (invariant-named)

| Commit | Scope |
|--------|--------|
| `6226d78` | FINDINGS + repro scaffold |
| `72ebd40` | A1/A2/C4/C5 — inv 4, 8 |
| `13bc1c3` | C1/C2/C3/C6 — inv 1, 4, 8 |
| `184c126` | B2–B8 — inv 2, 3, 4, 6, 7 |
| `690b3fc` | A3/A4/A5/A6 — inv 7 + Modal env |
| `f91b1a5` | Modal deploy fixes + B2 authorizer bootstrap + verified repro notes |

## Reproduce (post-fix — attacks must fail)

```powershell
cd glc_v1
uv sync --link-mode=copy
$env:GLC_ALLOW_FORCE_PAIR="1"
uv run pytest tests/ -q -m "not requires_live_api"

# In-process B leaks (expect all PASS = attack blocked):
uv run python scripts/s12_repro/inprocess_b_leaks.py

# C1 SSRF guard:
uv run python scripts/s12_repro/ssrf_c1.py

# HTTP local:
#   $env:GLC_HARDEN="1"; $env:GLC_DISABLE_DOCS="1"; uv run glc serve --host 127.0.0.1 --port 8111
#   curl without Bearer → 401; /docs → 404
```

### Verified 2026-07-18

**In-process:** B1–B8 and C1 SSRF — all PASS (attack blocked).

**Local HTTP** (`127.0.0.1:8111`, `GLC_HARDEN=1`):

| Check | Result |
|-------|--------|
| `POST /v1/chat` no auth | **401** |
| `GET /v1/status` no auth | **401** |
| `GET /docs` | **404** |
| `GET /openapi.json` | **404** |
| `GET /v1/status` + Bearer install token | **200** |

**Modal HTTP** ([live app](https://padmanabh275--glc-v1-gateway-fastapi-app.modal.run)):

| Check | Result |
|-------|--------|
| `POST /v1/chat` no auth | **401** |
| `GET /v1/status` no auth | **401** |
| `GET /docs` | **404** |
| `GET /openapi.json` | **404** |

## Deploy (Modal)

```powershell
uv run modal secret create glc-llm-keys OPENAI_API_KEY=sk-mock GEMINI_API_KEY=mock
uv run modal deploy modal_app.py
```

- URL: `https://padmanabh275--glc-v1-gateway-fastapi-app.modal.run`
- Dashboard: https://modal.com/apps/padmanabh275/main/deployed/glc-v1-gateway
- ASGI Function has **no** LLM secret; `llm_egress` holds keys and an outbound host allowlist.
- `max_containers=1` + audit/gateway DBs on Volume `/data/glc` (invariant 7).
- Image: `uv.lock` + `copy=True` local mounts; venv on `PYTHONPATH`.
