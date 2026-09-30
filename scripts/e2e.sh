#!/bin/bash
# Repeatable browser e2e on the LOCAL dev stack: reseed the synthetic Ensemble tenant, restart the API, run Playwright.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
set -a; . ./.env; set +a
PY="${PYTHON:-$ROOT/.venv/bin/python}"
export TEMPO_ENV=local TEMPO_DEV_IDP_ENABLED=true
export TEMPO_DATABASE_URL="postgresql+psycopg://tempo_app:${TEMPO_DB_APP_PASSWORD}@127.0.0.1:${POSTGRES_PORT:-5439}/tempo"
( cd services/tempo-api && "$PY" -m app.cli bootstrap-ensemble-demo --reset | grep -E '"result"' )
cd services/tempo-console && npx playwright test "$@"
