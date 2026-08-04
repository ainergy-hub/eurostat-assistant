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

if [ -z "${OPENROUTER_API_KEY:-}" ]; then
  echo "Missing OPENROUTER_API_KEY. Add it to .env or export it before running." >&2
  exit 1
fi

if [ -z "${OPENROUTER_MODEL_OPTIONS:-}" ]; then
  echo "Missing OPENROUTER_MODEL_OPTIONS. Define the comma-separated model list in .env." >&2
  exit 1
fi

EUROSTAT_DEFAULT_MODEL="${OPENROUTER_MODEL_OPTIONS%%,*}"

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

echo "Starting Eurostat Assistant on http://${HOST}:${PORT}"
echo "Using OpenRouter model: ${EUROSTAT_DEFAULT_MODEL}"

exec uv run uvicorn app.main:app \
  --host "$HOST" \
  --port "$PORT" \
  --proxy-headers \
  --forwarded-allow-ips="*"
