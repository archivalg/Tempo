"""Model monitoring endpoints — §15.2, Phase F."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.monitoring import check_drift, compute_model_monitoring
from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["monitoring"])


@router.get("/monitoring/models")
def get_model_monitoring(
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not context.has_permission("labour.read"):
        raise AuthForbidden("caller lacks labour.read permission required to view model monitoring")
    return {"models": compute_model_monitoring(db, context.tenant_id)}


@router.post("/monitoring/models/drift-check")
def run_drift_check(
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """On-demand drift check — see app.core.monitoring's docstring for why
    this isn't a background job. Safe to call repeatedly; re-flags the same
    drift each time until enough new runs shift the comparison windows."""
    if not context.has_permission("labour.configure"):
        raise AuthForbidden("caller lacks labour.configure permission required to run a drift check")
    return {"drift_signals": check_drift(db, context.tenant_id)}
