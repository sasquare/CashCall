#!/bin/sh
set -e

echo "[entrypoint] Running Alembic migrations…"
alembic upgrade head

# Optionally seed initial data in development
if [ "${APP_ENV:-development}" = "development" ] && [ "${SEED_DB:-false}" = "true" ]; then
    echo "[entrypoint] Seeding development data…"
    python scripts/seed.py
fi

echo "[entrypoint] Starting uvicorn…"
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers "${WORKERS:-2}" \
    --proxy-headers \
    --forwarded-allow-ips="*" \
    --no-access-log
