"""Tempo Optimisation Service — Phase 0 scaffold.

See docs/roadmap.md (repo root) for what this phase covers and what's next,
and services/tempo-api/README.md for how to run it and a section-by-section
map back to the Integration Spec.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as v1_router
from app.config import settings, validate_settings
from app.db import init_db
from app.errors import TempoError, tempo_error_handler


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_settings(settings)
    init_db()
    from app.core.jobs import start_background_loop
    start_background_loop()   # only when TEMPO_JOBS_ENABLED=true
    yield


# The framework's own /docs, /redoc and /openapi.json would publish every internal route (platform, auth, admin). They are off; the supported
# public API is documented by app/api/v1/public_docs.py from an allow-list.
app = FastAPI(title=settings.service_name, version="0.1.0-phase0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_exception_handler(TempoError, tempo_error_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.console_cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Idempotency-Key", "X-CSRF-Token", "X-Tempo-Tenant", "X-Correlation-Id"],
    expose_headers=["Content-Disposition"],
)


@app.middleware("http")
async def attach_correlation_id(request: Request, call_next):
    request.state.correlation_id = request.headers.get("X-Correlation-Id", f"cor_{uuid.uuid4().hex[:20]}")
    response = await call_next(request)
    response.headers["X-Correlation-Id"] = request.state.correlation_id
    return response


@app.get("/readyz", tags=["ops"])
def readyz() -> dict[str, str]:
    """Readiness: the runtime role can reach PostgreSQL and the code's migration head is known."""
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    from app import db as db_module
    from app.errors import TempoError

    class NotReady(TempoError):
        status, error_code, title = 503, "TEMPO-SVC-503", "Not ready"

    try:
        with db_module.engine.connect() as c:
            who = c.execute(text("SELECT current_user")).scalar()
            applied = c.execute(text("SELECT to_regclass('public.alembic_version') IS NOT NULL")).scalar()
        head = ScriptDirectory.from_config(Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))).get_current_head()
    except Exception as exc:  # noqa: BLE001
        raise NotReady("database not reachable") from exc
    if not applied:
        raise NotReady("schema not migrated")
    # deliberately terse: an unauthenticated endpoint must not disclose role names or schema versions
    return {"status": "ready", "database": "postgresql"}


@app.get("/healthz", tags=["ops"])
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": settings.service_name}


app.include_router(v1_router, prefix=settings.api_base_path)
