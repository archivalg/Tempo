"""Editing a person's kiosk badge number, active status and skills (roadmap M2/M3 gaps). Needs the configure permission and the worker's site in the caller's grants."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import auth, timeclock
from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden, PolicyConflict, RunNotFound
from app.models.canonical import SkillCertification, Worker
from app.models.directory import WorkerPerson
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["people"])


def _worker(db: Session, ctx: RequestContext, worker_id: str) -> Worker:
    if not ctx.has_permission("labour.configure"):
        raise AuthForbidden("caller lacks labour.configure")
    w = db.get(Worker, worker_id)
    if w is None or w.tenant_id != ctx.tenant_id or w.home_site not in ctx.site_ids:
        raise RunNotFound("worker not found or not visible in caller scope")
    return w


class WorkerPatch(BaseModel):
    badge_no: str | None = Field(default=None, min_length=1, max_length=24, pattern=r"^[0-9]+$")
    status: str | None = Field(default=None, pattern="^(active|inactive)$")


@router.patch("/workers/{worker_id}")
def patch_worker(worker_id: str, body: WorkerPatch, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    w = _worker(db, ctx, worker_id)
    p = db.get(WorkerPerson, worker_id)
    if body.badge_no is not None:
        clash = db.scalar(select(WorkerPerson.worker_id).where(WorkerPerson.tenant_id == ctx.tenant_id, WorkerPerson.employee_no == body.badge_no, WorkerPerson.worker_id != worker_id).limit(1))
        if clash:
            raise PolicyConflict("another person already has that badge number; badge numbers must be unique because the kiosk identifies people by them")
        if p is None:
            raise PolicyConflict("this worker has no personal record to attach a badge number to; load them through the staff upload first")
        p.employee_no = body.badge_no
        auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="worker.badge_set", decision="allowed", session_ref=worker_id, correlation_id=ctx.correlation_id)
    if body.status is not None and body.status != w.status:
        if body.status == "inactive" and timeclock.open_session(db, ctx.tenant_id, worker_id) is not None:
            raise PolicyConflict("this person is clocked in. Clock them out (or correct the session) before making them inactive")
        w.status = body.status
        auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action=f"worker.{body.status}", decision="allowed", session_ref=worker_id, correlation_id=ctx.correlation_id)
    db.flush()
    return {"worker_id": worker_id, "status": w.status, "badge_no": p.employee_no if p else None}


class SkillIn(BaseModel):
    skill_code: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_ -]+$")


def _skills(db: Session, ctx: RequestContext, worker_id: str) -> list[str]:
    return sorted(db.scalars(select(SkillCertification.skill_code).where(SkillCertification.tenant_id == ctx.tenant_id, SkillCertification.worker_id == worker_id)))


@router.get("/workers/{worker_id}/skills")
def list_skills(worker_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    _worker(db, ctx, worker_id)
    return {"worker_id": worker_id, "skills": _skills(db, ctx, worker_id)}


@router.post("/workers/{worker_id}/skills", status_code=201)
def add_skill(worker_id: str, body: SkillIn, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """Adds a skill the person is qualified for (lower-cased, so it matches roles in rosters). Adding one they already hold changes nothing."""
    _worker(db, ctx, worker_id)
    code = body.skill_code.strip().lower()
    if code not in _skills(db, ctx, worker_id):
        db.add(SkillCertification(tenant_id=ctx.tenant_id, worker_id=worker_id, skill_code=code, valid_from=datetime.now(timezone.utc)))
        auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="worker.skill_add", decision="allowed", reason_code=code, session_ref=worker_id, correlation_id=ctx.correlation_id)
        db.flush()
    return {"worker_id": worker_id, "skills": _skills(db, ctx, worker_id)}


@router.delete("/workers/{worker_id}/skills/{skill_code}")
def remove_skill(worker_id: str, skill_code: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """Removes a skill. Rosters already published are not changed; new drafts and validation stop counting it."""
    _worker(db, ctx, worker_id)
    rows = list(db.scalars(select(SkillCertification).where(SkillCertification.tenant_id == ctx.tenant_id, SkillCertification.worker_id == worker_id, SkillCertification.skill_code == skill_code.strip().lower())))
    if not rows:
        raise RunNotFound("the person does not hold that skill")
    for r in rows:
        db.delete(r)
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="worker.skill_remove", decision="allowed", reason_code=skill_code.lower(), session_ref=worker_id, correlation_id=ctx.correlation_id)
    db.flush()
    return {"worker_id": worker_id, "skills": _skills(db, ctx, worker_id)}
