#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ -f ".env" ]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

# uv-managed Python installations on macOS may not be able to build some
# certificate chains from the system CA file. Prefer certifi's maintained CA
# bundle for local processes unless the user has supplied a custom trust store.
if [ -z "${SSL_CERT_FILE:-}" ] && [ -x ".venv/bin/python" ]; then
  LOCAL_CERT_BUNDLE="$(".venv/bin/python" -m certifi 2>/dev/null || true)"
  if [ -n "$LOCAL_CERT_BUNDLE" ] && [ -f "$LOCAL_CERT_BUNDLE" ]; then
    export SSL_CERT_FILE="$LOCAL_CERT_BUNDLE"
  fi
fi

if [ -z "${OPENROUTER_API_KEY:-}" ]; then
  echo "Missing OPENROUTER_API_KEY. Add it to .env or export it before running." >&2
  exit 1
fi

if [ -z "${OPENROUTER_MODEL_OPTIONS:-}" ]; then
  echo "Missing OPENROUTER_MODEL_OPTIONS. Define the comma-separated model list in .env." >&2
  exit 1
fi

if [ -z "${APP_PASSWORD:-}" ] && [ "${APP_ALLOW_UNLOCKED:-}" != "true" ]; then
  echo "Missing APP_PASSWORD. Set it in .env, or set APP_ALLOW_UNLOCKED=true to run unlocked in a trusted environment." >&2
  exit 1
fi

EUROSTAT_DEFAULT_MODEL="${OPENROUTER_MODEL_OPTIONS%%,*}"

PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"

echo "Starting Eurostat Assistant on http://${HOST}:${PORT}"
echo "Using OpenRouter model: ${EUROSTAT_DEFAULT_MODEL}"

# Uvicorn trusts proxy headers only from 127.0.0.1 unless FORWARDED_ALLOW_IPS
# lists the addresses of a reverse proxy in front of this server.
exec uv run uvicorn app.main:app \
  --host "$HOST" \
  --port "$PORT"
