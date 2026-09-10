"""Problem-details error contract — §8.6, Appendix B."""
from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

PROBLEM_BASE = "https://tempo.ensemblesolutions.com.au/problems"


class TempoError(Exception):
    """Base for every Appendix B error code. `status` and `error_code` are
    fixed per subclass so a caller can dispatch on error_code alone."""

    status: int = 500
    error_code: str = "TEMPO-SVC-001"
    title: str = "Internal error"
    retryable: bool = False

    def __init__(self, detail: str, issues: list[dict[str, Any]] | None = None):
        super().__init__(detail)
        self.detail = detail
        self.issues = issues or []


class ScopeError(TempoError):
    status = 400
    error_code = "TEMPO-SCOPE-001"
    title = "Missing/contradictory tenant, site or customer scope"


class AuthInvalid(TempoError):
    status = 401
    error_code = "TEMPO-AUTH-001"
    title = "Invalid or expired identity"


class AuthForbidden(TempoError):
    status = 403
    error_code = "TEMPO-AUTH-002"
    title = "Permission or scope denied"


class SnapshotStale(TempoError):
    status = 409
    error_code = "TEMPO-DATA-001"
    title = "Canonical snapshot changed or config version stale"
    retryable = True


class DataNotReady(TempoError):
    status = 422
    error_code = "TEMPO-DATA-004"
    title = "Required data is not ready"


class PolicyConflict(TempoError):
    status = 422
    error_code = "TEMPO-POLICY-001"
    title = "Constraint/policy conflict"


class RunNotFound(TempoError):
    status = 404
    error_code = "TEMPO-RUN-001"
    title = "Run not found or not visible in caller scope"


class RunTerminal(TempoError):
    status = 409
    error_code = "TEMPO-RUN-002"
    title = "Run is terminal or cannot transition as requested"


class QuotaExceeded(TempoError):
    status = 429
    error_code = "TEMPO-RUN-003"
    title = "Tenant/workload quota exceeded"
    retryable = True


class RunTypeNotImplemented(TempoError):
    status = 501
    error_code = "TEMPO-RUN-004"
    title = "Run type is not yet implemented for this phase"


class SolverInfeasible(TempoError):
    status = 422
    error_code = "TEMPO-SOLVER-001"
    title = "Model infeasible"


class ActionTokenExpired(TempoError):
    status = 409
    error_code = "TEMPO-ACTION-001"
    title = "Recommendation, approval or action token expired"
    retryable = False


class ActionVersionDrift(TempoError):
    status = 409
    error_code = "TEMPO-ACTION-002"
    title = "Source version changed; revalidate and reconfirm"
    retryable = False


class ActionSourceRejected(TempoError):
    status = 502
    error_code = "TEMPO-ACTION-003"
    title = "Source rejected or failed; inspect action status"


class ActionNotFound(TempoError):
    """Not one of the Integration Spec's four named TEMPO-ACTION-00x codes
    (§8.6's error catalogue only defines 001-004) — a pragmatic extension
    for a case the spec doesn't name, same as ZoneBacklog/ActivityRoleZoneMap
    extend the canonical model where the spec's own entities don't cover a
    gap this codebase actually needs to handle.
    """

    status = 404
    error_code = "TEMPO-ACTION-005"
    title = "Action or recommendation not found or not visible in caller scope"


class ActionTypeMismatch(TempoError):
    status = 400
    error_code = "TEMPO-ACTION-006"
    title = "action_type is not valid for the referenced recommendation"


class AttendanceStateConflict(TempoError):
    """Native capture (app/api/v1/attendance.py) has no dedicated error
    codes in the Integration Spec's §8.6 catalogue — that catalogue is
    written entirely from the Overlay/Prime side, which never clocks a
    worker in or out itself. TEMPO-ATTENDANCE-00x is a pragmatic
    extension, same class as TEMPO-ACTION-005/006.
    """

    status = 409
    error_code = "TEMPO-ATTENDANCE-001"
    title = "Worker already has an open attendance session, or has none to close"


class GeofenceViolation(TempoError):
    status = 422
    error_code = "TEMPO-ATTENDANCE-002"
    title = "Clock-in location is outside the site's configured geofence"


class ProviderNotFound(TempoError):
    """The Integration Spec's §8.6 error catalogue predates the Labour
    Provider role entirely (see app/models/canonical.py's LabourProvider
    docstring) — a pragmatic extension, same class as TEMPO-ACTION-005/006
    and TEMPO-ATTENDANCE-001/002.
    """

    status = 404
    error_code = "TEMPO-PROVIDER-001"
    title = "Labour provider not found, or worker not supplied by it, or not visible in caller scope"


def problem_response(request: Request, error: TempoError) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", None)
    body = {
        "type": f"{PROBLEM_BASE}/{error.error_code.lower()}",
        "title": error.title,
        "status": error.status,
        "detail": error.detail,
        "instance": str(request.url.path),
        "error_code": error.error_code,
        "correlation_id": correlation_id,
        "issues": error.issues,
        "retryable": error.retryable,
    }
    return JSONResponse(status_code=error.status, content=body)


async def tempo_error_handler(request: Request, exc: TempoError) -> JSONResponse:
    return problem_response(request, exc)
