"""Audit record writer — §14.2."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.runs import AuditRecord
from app.schemas.tenancy import RequestContext


def write_audit(
    db: Session,
    context: RequestContext,
    request_name: str,
    outcome: str,
    parameters: dict[str, Any] | None = None,
    run_id: str | None = None,
    evidence_ref: str | None = None,
) -> AuditRecord:
    record = AuditRecord(
        tenant_id=context.tenant_id,
        actor_user_id=context.user_id,
        purpose=context.purpose,
        request_name=request_name,
        parameters=_redact(parameters or {}),
        run_id=run_id,
        evidence_ref=evidence_ref,
        correlation_id=context.correlation_id,
        outcome=outcome,
    )
    db.add(record)
    db.flush()
    return record


_PROTECTED_FIELDS = {"pay_code", "rate", "biometric", "tax_file_number"}


def _redact(parameters: dict[str, Any]) -> dict[str, Any]:
    """§14.2: 'normalised parameters (with protected fields redacted)'."""
    return {key: ("[redacted]" if key in _PROTECTED_FIELDS else value) for key, value in parameters.items()}
