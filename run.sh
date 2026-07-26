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

if [ -z "${E2B_API_KEY:-}" ]; then
  echo "Missing E2B_API_KEY. Add it to .env or export it before running." >&2
  exit 1
fi

if [ -z "${OPENROUTER_API_KEY:-}" ]; then
  echo "Missing OPENROUTER_API_KEY. Add it to .env or export it before running." >&2
  exit 1
fi

if [ -z "${OPENROUTER_MODEL:-}" ] && [ -n "${OPENAI_MODEL:-}" ]; then
  export OPENROUTER_MODEL="$OPENAI_MODEL"
fi

if [ -z "${OPENROUTER_MODEL:-}" ]; then
  export OPENROUTER_MODEL="openai/gpt-4.1-mini"
fi

case "$OPENROUTER_MODEL" in
  */*) ;;
  *) export OPENROUTER_MODEL="openai/$OPENROUTER_MODEL" ;;
esac

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

echo "Starting Eurostat Lens on http://${HOST}:${PORT}"
echo "Using OpenRouter model: ${OPENROUTER_MODEL}"

exec uv run uvicorn app.main:app \
  --host "$HOST" \
  --port "$PORT" \
  --proxy-headers \
  --forwarded-allow-ips="*"
