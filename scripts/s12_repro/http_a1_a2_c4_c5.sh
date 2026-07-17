#!/usr/bin/env bash
# HTTP repro for A1, A2, C4, C5 — expect 401 without token after harden.
set -euo pipefail
BASE="${GLC_BASE:-http://127.0.0.1:8111}"
TOKEN="${GLC_TOKEN:-}"

echo "== A1: POST /v1/chat without auth (expect 401) =="
curl -sS -o /tmp/glc_chat.json -w "HTTP %{http_code}\n" \
  -X POST "$BASE/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"ping","max_tokens":8}' || true
head -c 200 /tmp/glc_chat.json; echo

echo "== A2: GET /v1/status without auth (expect 401) =="
curl -sS -o /tmp/glc_status.json -w "HTTP %{http_code}\n" "$BASE/v1/status" || true
head -c 200 /tmp/glc_status.json; echo

echo "== A2: GET /docs (expect 404 when docs disabled) =="
curl -sS -o /dev/null -w "HTTP %{http_code}\n" "$BASE/docs" || true

echo "== A2: GET /openapi.json (expect 404 when disabled) =="
curl -sS -o /dev/null -w "HTTP %{http_code}\n" "$BASE/openapi.json" || true

if [[ -n "$TOKEN" ]]; then
  echo "== Authed chat (expect not 401) =="
  curl -sS -o /tmp/glc_chat_ok.json -w "HTTP %{http_code}\n" \
    -X POST "$BASE/v1/chat" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"prompt":"ping","max_tokens":8}' || true
  head -c 300 /tmp/glc_chat_ok.json; echo
fi
