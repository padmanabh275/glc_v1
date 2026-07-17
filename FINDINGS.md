# Session 12 Part 1 — Findings

Hardened `glc_v1` against Section 6 (A/C) and Section 7 (B) findings.
Invariant map: Architecture moves 1–6 ([`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)),
plus **7 = append-only / single-writer audit integrity**, **8 = rate limits + hard budgets**.

Repro scripts: [`scripts/s12_repro/`](scripts/s12_repro/). Use **mock keys only**.

| ID | Summary | Invariant | Status | Fix |
|----|---------|-----------|--------|-----|
| A1 | Public data plane, no auth | 4 | fixed | `require_data_plane` on chat/speak/transcribe |
| A2 | Info disclosure + Swagger | 4 | fixed | Auth on status/providers/…; `GLC_DISABLE_DOCS=1` |
| A3 | No egress wall | S12 env | fixed | `llm_egress` Modal Function + host allowlist |
| A4 / B1 | One Secret / env keys | S12 env | fixed | Secrets only on egress Fn; `scrub_provider_secrets` |
| A5 | Non-reproducible image | supply-chain | fixed | `uv.lock` + pinned base in `modal_app.py` |
| A6 | Audit SQLite + autoscale | 7 | fixed | `max_containers=1` + Volume.commit |
| B2 | Audit DELETE/DROP | 3, 6, 7 | fixed | SQLite authorizer under `GLC_HARDEN` |
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

## Reproduce

```powershell
cd glc_v1
uv sync --link-mode=copy
$env:GLC_ALLOW_FORCE_PAIR="1"
uv run pytest tests/ -q -m "not requires_live_api"

# In-process B leaks (expect all PASS):
uv run python scripts/s12_repro/inprocess_b_leaks.py

# C1 SSRF guard:
uv run python scripts/s12_repro/ssrf_c1.py

# HTTP (local gateway):
#   $env:GLC_HARDEN="1"; $env:GLC_DISABLE_DOCS="1"; uv run glc serve
#   $env:GLC_BASE="http://127.0.0.1:8111"
#   $env:GLC_TOKEN=(uv run glc token)
#   bash scripts/s12_repro/http_a1_a2_c4_c5.sh
```

Unauthenticated `POST /v1/chat` → **401**. Authed calls proceed (or fail upstream with generic `upstream_error`, not raw provider text).

## Deploy (Modal)

```powershell
uv run modal secret create glc-llm-keys OPENAI_API_KEY=sk-mock GEMINI_API_KEY=mock
uv run modal deploy modal_app.py
```

ASGI Function has **no** LLM secret; `llm_egress` holds keys and an outbound host allowlist. `max_containers=1` protects SQLite audit (invariant 7).
