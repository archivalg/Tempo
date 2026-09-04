"""Tempo Optimisation Service — Phase 0 scaffold.

See docs/roadmap.md (repo root) for what this phase covers and what's next,
and services/tempo-api/README.md for how to run it and a section-by-section
map back to the Integration Spec.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.api.v1.router import router as v1_router
from app.config import settings
from app.db import init_db
from app.errors import TempoError, tempo_error_handler


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.service_name, version="0.1.0-phase0", lifespan=lifespan)
app.add_exception_handler(TempoError, tempo_error_handler)


@app.middleware("http")
async def attach_correlation_id(request: Request, call_next):
    request.state.correlation_id = request.headers.get("X-Correlation-Id", f"cor_{uuid.uuid4().hex[:20]}")
    response = await call_next(request)
    response.headers["X-Correlation-Id"] = request.state.correlation_id
    return response


@app.get("/healthz", tags=["ops"])
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": settings.service_name}


app.include_router(v1_router, prefix=settings.api_base_path)
