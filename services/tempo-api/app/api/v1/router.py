from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import commit_before_response

from app.api.v1 import auth, availability as availability_api, demand, devices, handoffs, imports as imports_api, service_clients, notifications, operations, platform, platform_billing, billing as billing_api, planning_rules, reports, rosters, timeclock, users, actions, attendance, ingestion, monitoring, onboarding, providers, readiness, runs

router = APIRouter(dependencies=[Depends(commit_before_response, scope="function")])
router.include_router(auth.router)
router.include_router(devices.router)
router.include_router(platform.router)
router.include_router(operations.router)
router.include_router(rosters.router)
router.include_router(timeclock.router)  # before reports: its exact export path must win over reports' /exports/{kind}.csv
router.include_router(reports.router)
router.include_router(demand.router)
router.include_router(notifications.router)
router.include_router(handoffs.router)
router.include_router(imports_api.router)
router.include_router(service_clients.router)
router.include_router(users.router)
router.include_router(readiness.router)
router.include_router(runs.router)
router.include_router(actions.router)
router.include_router(onboarding.router)
router.include_router(monitoring.router)
router.include_router(attendance.router)
router.include_router(planning_rules.router)
router.include_router(platform_billing.router)
router.include_router(billing_api.router)
router.include_router(availability_api.router)
router.include_router(providers.router)
router.include_router(ingestion.router)
