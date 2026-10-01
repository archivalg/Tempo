#!/bin/bash
# Local development stack: API :8017 + console :5174 against the compose PostgreSQL (127.0.0.1:5439). Dev identity ON — loopback only.
# Needs ./.env (see .env.example) and a Python 3.12 venv: uv venv --python 3.12 .venv && VIRTUAL_ENV=.venv uv pip install -r services/tempo-api/requirements.txt
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
set -a; . ./.env; set +a
PY="${PYTHON:-$ROOT/.venv/bin/python}"
export TEMPO_ENV=local TEMPO_DEV_IDP_ENABLED=true TEMPO_SESSION_COOKIE_SECURE=false
export TEMPO_DATABASE_URL="postgresql+psycopg://tempo_app:${TEMPO_DB_APP_PASSWORD}@127.0.0.1:${POSTGRES_PORT:-5439}/${E2E_DB:-tempo_e2e}"
export TEMPO_DATABASE_MIGRATION_URL="postgresql+psycopg://tempo_owner:${TEMPO_DB_OWNER_PASSWORD}@127.0.0.1:${POSTGRES_PORT:-5439}/${E2E_DB:-tempo_e2e}"
export TEMPO_CONSOLE_CORS_ORIGINS="http://127.0.0.1:5174"
( cd services/tempo-api && "$PY" -m alembic upgrade head )
( cd services/tempo-api && nohup "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8017 > /tmp/tempo-api-dev.log 2>&1 & )
( cd services/tempo-console && VITE_API_BASE_URL=http://127.0.0.1:8017/v1 nohup npx vite --host 127.0.0.1 --port 5174 > /tmp/tempo-console-dev.log 2>&1 & )
echo "API http://127.0.0.1:8017  console http://127.0.0.1:5174  (logs in /tmp/tempo-*-dev.log)"
