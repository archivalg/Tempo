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
