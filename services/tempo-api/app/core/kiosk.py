"""Kiosk device identity and worker-credential abuse controls (blueprint §3.3, §5.1).

A kiosk authenticates as an *enrolled device* bound to one tenant and a finite set of
sites. Worker PIN/NFC identifies who is using the device; it can never establish or
change the device's tenant or site scope (SEC-13).

* Enrolment: an admin creates a device and receives a one-time code (shown once, only its
  digest stored, 15 min expiry, single use). The device redeems it for a device credential
  `tkd_<device_id>.<secret>`; only an HMAC digest of the secret is stored.
* PINs are stored with Argon2id (per-PIN salt) and verified against the worker the kiosk
  names; there is no lookup-by-hash. Wrong/unknown worker/PIN give one indistinguishable error.
* Lockouts: 5 consecutive failures lock the worker credential for 15 minutes; 20 failures
  on a device within 10 minutes lock the device for 5 minutes. Both write security audit events.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import auth
from app.db import begin_auth_lookup, bind_sites, bind_tenant
from app.errors import AuthForbidden, AuthInvalid
from app.models.attendance import WorkerCredential
from app.models.canonical import Worker
from app.models.directory import WorkerPerson
from app.models.identity import KioskDevice, Tenant

_ph = PasswordHasher()  # Argon2id defaults (argon2-cffi: time_cost=3, memory_cost=64MiB, parallelism=4)
ENROL_TTL = timedelta(minutes=15)
WORKER_MAX_FAILS, WORKER_LOCK = 5, timedelta(minutes=15)
DEVICE_MAX_FAILS, DEVICE_WINDOW, DEVICE_LOCK = 20, timedelta(minutes=10), timedelta(minutes=5)

# Constant-cost dummy so unknown-worker and wrong-PIN take the same time.
_DUMMY_HASH = _ph.hash("tempo-dummy-pin")


def hash_pin(pin: str) -> str:
    return _ph.hash(pin)


def verify_pin(stored: str | None, pin: str) -> bool:
    try:
        return _ph.verify(stored or _DUMMY_HASH, pin) and stored is not None
    except (VerificationError, InvalidHashError):
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def _device_digest(secret: str) -> str:
    return hmac.new(auth._signing_key().encode(), secret.encode(), hashlib.sha256).hexdigest()


def new_enrolment_code(device: KioskDevice) -> str:
    code = secrets.token_urlsafe(9)
    device.enrolment_code_digest = auth.digest(code)
    device.enrolment_expires_at = _now() + ENROL_TTL
    device.status = "pending"
    device.enrolled_at = None
    device.credential_reference = None
    return f"{device.device_id}.{code}"


def redeem_enrolment(db: Session, presented: str, *, correlation_id: str) -> tuple[KioskDevice, str]:
    begin_auth_lookup(db)
    try:
        device_id, code = presented.split(".", 1)
    except ValueError:
        raise AuthInvalid("invalid enrolment code") from None
    device = db.get(KioskDevice, device_id)
    ok = (device is not None and device.status == "pending" and device.enrolment_code_digest is not None
          and _aware(device.enrolment_expires_at) > _now()
          and hmac.compare_digest(device.enrolment_code_digest, auth.digest(code)))
    if not ok:
        auth.audit(db, actor_type="kiosk", actor_id=(device_id or "?")[:64], action="kiosk.enrol", decision="denied",
                   tenant_id=device.tenant_id if device else None, reason_code="bad_or_expired_code", correlation_id=correlation_id)
        db.commit()
        raise AuthInvalid("invalid enrolment code")
    bind_tenant(db, device.tenant_id)  # writes happen under the device's tenant policy, not the auth phase
    secret = secrets.token_urlsafe(32)
    device.credential_reference = f"hmac-sha256:{_device_digest(secret)}"
    device.enrolment_code_digest = None  # single use
    device.enrolment_expires_at = None
    device.status = "active"
    device.enrolled_at = _now()
    auth.audit(db, actor_type="kiosk", actor_id=device.device_id, action="kiosk.enrol", decision="allowed",
               tenant_id=device.tenant_id, correlation_id=correlation_id)
    return device, f"tkd_{device.device_id}.{secret}"


@dataclass(frozen=True)
class KioskContext:
    device_id: str
    tenant_id: str
    site_ids: list[str]
    correlation_id: str


def authenticate_device(db: Session, token: str, correlation_id: str) -> KioskContext:
    """Verifies the device credential, then binds the DB session to the device's tenant."""
    if not token.startswith("tkd_") or "." not in token:
        raise AuthInvalid("invalid device credential")
    begin_auth_lookup(db)
    device_id, secret = token[4:].split(".", 1)
    device = db.get(KioskDevice, device_id)
    ref = (device.credential_reference or "") if device else ""
    good = ref.startswith("hmac-sha256:") and hmac.compare_digest(ref[12:], _device_digest(secret))
    if device is None or not good or device.status != "active" or device.disabled_at is not None:
        raise AuthInvalid("invalid device credential")
    tenant = db.get(Tenant, device.tenant_id)
    if tenant is None or tenant.status != "active":
        raise AuthInvalid("invalid device credential")
    if _aware(device.locked_until) and _aware(device.locked_until) > _now():
        raise AuthForbidden("device is temporarily locked")
    if not device.site_ids:
        raise AuthForbidden("device has no site binding")
    tenant_id, sites = device.tenant_id, list(device.site_ids)
    bind_tenant(db, tenant_id)
    bind_sites(db, sites)  # the device can only ever see its own sites' rows
    device.last_seen_at = _now()
    return KioskContext(device.device_id, tenant_id, sites, correlation_id)


def _record_failure(db: Session, ctx: KioskContext, worker_id: str | None, cred: WorkerCredential | None) -> None:
    now = _now()
    device = db.get(KioskDevice, ctx.device_id)
    if cred is not None:
        cred.failed_attempts += 1
        if cred.failed_attempts >= WORKER_MAX_FAILS:
            cred.locked_until = now + WORKER_LOCK
            auth.audit(db, actor_type="kiosk", actor_id=ctx.device_id, tenant_id=ctx.tenant_id, action="kiosk.worker_locked",
                       decision="applied", reason_code=f"worker={worker_id}", correlation_id=ctx.correlation_id)
    if device is not None:
        ws = _aware(device.failed_window_start)
        if ws is None or now - ws > DEVICE_WINDOW:
            device.failed_window_start, device.failed_count = now, 0
        device.failed_count += 1
        if device.failed_count >= DEVICE_MAX_FAILS:
            device.locked_until = now + DEVICE_LOCK
            auth.audit(db, actor_type="kiosk", actor_id=ctx.device_id, tenant_id=ctx.tenant_id, action="kiosk.device_locked",
                       decision="applied", reason_code="too_many_failures", correlation_id=ctx.correlation_id)


def verify_worker(db: Session, ctx: KioskContext, *, method: str, worker_id: str | None, pin: str | None,
                  nfc_tag_id: str | None, worker_no: str | None = None, qr_token: str | None = None, consume_qr: bool = True) -> Worker:
    """Identify the worker at this kiosk. Failure is deliberately non-specific."""
    generic = AuthInvalid("credential not recognised")
    cred: WorkerCredential | None = None
    if method == "pin" and worker_no and not worker_id:
        # Badge number -> worker, scoped to the device's tenant. Unknown numbers take the same path as a wrong PIN.
        person = db.scalar(select(WorkerPerson).where(WorkerPerson.tenant_id == ctx.tenant_id, WorkerPerson.employee_no == worker_no))
        worker_id = person.worker_id if person else None
    if method == "qr":
        # A rotating, single-use code shown in the employee's own app; the kiosk's tenant is the only tenant it can be redeemed in.
        from app.core import kiosk_qr
        try:
            qr_worker = kiosk_qr.redeem(db, ctx.tenant_id, qr_token or "", consume=consume_qr)
        except AuthInvalid:
            _record_failure(db, ctx, None, None)
            db.commit()
            raise
        worker = db.get(Worker, qr_worker)
        if worker is None or worker.tenant_id != ctx.tenant_id or worker.status != "active":
            raise generic
        if worker.home_site not in ctx.site_ids and not _has_site_eligibility(db, worker, ctx):
            raise generic
        db.commit()   # the code is spent even if the tap then fails
        return worker
    if method == "pin":
        cred = db.get(WorkerCredential, worker_id) if worker_id else None
        if cred is not None and cred.tenant_id != ctx.tenant_id:
            cred = None
        if cred is not None and _aware(cred.locked_until) and _aware(cred.locked_until) > _now():
            raise AuthForbidden("credential is temporarily locked; see a supervisor")
        ok = verify_pin(cred.pin_hash if cred else None, pin or "")
    else:
        cred = db.scalar(select(WorkerCredential).where(WorkerCredential.tenant_id == ctx.tenant_id,
                                                        WorkerCredential.nfc_tag_id == nfc_tag_id))
        ok = cred is not None and bool(nfc_tag_id)
    if not ok:
        _record_failure(db, ctx, worker_id, cred if method == "pin" else None)
        db.commit()  # failures must persist even though the request is rejected
        raise generic
    worker = db.get(Worker, cred.worker_id)
    if worker is None or worker.tenant_id != ctx.tenant_id or worker.status != "active":
        raise generic
    if worker.home_site not in ctx.site_ids and not _has_site_eligibility(db, worker, ctx):
        raise generic
    cred.failed_attempts, cred.locked_until = 0, None
    return worker


def _has_site_eligibility(db: Session, worker: Worker, ctx: KioskContext) -> bool:
    # Workers are bound to a home site today; cross-site eligibility arrives with the site-eligibility model.
    return False
