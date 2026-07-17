# GLC v1 Dashboard (static)

Local gateway UI served at http://127.0.0.1:8111/ when `uv run glc serve` is running.

## Files

| File            | Role |
|-----------------|------|
| `dashboard.html`| Main dashboard — channels, WS tester, control, LLM, voice |
| `app.css`       | Dark theme, per-channel accent colors, compact channel grid |
| `app.js`        | Catalogue API, toggles, WebSocket chat tester |
| `help.html`     | Help / quick reference |

## Dashboard highlights

- **15 channel cards** — enable/disable, brand-colored accents, 5-column compact grid (wide screens).
- **Live channel tester** — chat bubbles (sent/reply/errors) + collapsible raw JSON log.
- **Stats** — catalogue count, enabled, live WS, paired users.
- **Control plane tab** — presence, pairing, kill switch.

## WS tester IDs (do not duplicate)

- `ws-chat-thread` — chat message panel
- `ws-thread-id` — optional Signal group / thread id input
- `ws-user-id` — sender phone number
- `ws-channel` — channel select

## Full setup reference

See `local_testing/SETUP_DETAILS.md` for phone numbers, `allowed_senders`, signal-cli, and troubleshooting.
