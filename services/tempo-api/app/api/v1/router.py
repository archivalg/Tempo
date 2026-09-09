from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import actions, readiness, runs

router = APIRouter()
router.include_router(readiness.router)
router.include_router(runs.router)
router.include_router(actions.router)
