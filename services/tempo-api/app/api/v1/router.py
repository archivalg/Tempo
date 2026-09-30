from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import auth, devices, operations, platform, actions, attendance, ingestion, monitoring, onboarding, providers, readiness, runs

router = APIRouter()
router.include_router(auth.router)
router.include_router(devices.router)
router.include_router(platform.router)
router.include_router(operations.router)
router.include_router(readiness.router)
router.include_router(runs.router)
router.include_router(actions.router)
router.include_router(onboarding.router)
router.include_router(monitoring.router)
router.include_router(attendance.router)
router.include_router(providers.router)
router.include_router(ingestion.router)
