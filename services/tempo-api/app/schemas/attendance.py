"""Native capture contracts — Business Spec §4/§5 (Standalone mode)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ClockMethod = Literal["pin", "nfc"]


class GpsCoordinates(BaseModel):
    """The device's position at the tap, or why it could not be had (`error`: denied | unavailable)."""
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100000)
    error: Literal["denied", "unavailable"] | None = None


class CredentialEnrollRequest(BaseModel):
    worker_id: str
    pin: str | None = None
    nfc_tag_id: str | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "CredentialEnrollRequest":
        if not self.pin and not self.nfc_tag_id:
            raise ValueError("at least one of pin or nfc_tag_id is required")
        if self.pin and not (self.pin.isdigit() and 4 <= len(self.pin) <= 8):
            raise ValueError("a PIN is 4 to 8 digits")
        return self


class CredentialEnrollResponse(BaseModel):
    worker_id: str
    has_pin: bool
    has_nfc: bool


class ClockInRequest(BaseModel):
    site_id: str | None = None  # kiosk: defaults to the device's only site; must be one of its sites
    method: ClockMethod
    worker_id: str | None = None
    worker_no: str | None = None  # numeric badge/employee number typed at the kiosk
    pin: str | None = None
    nfc_tag_id: str | None = None
    gps: GpsCoordinates | None = None

    @model_validator(mode="after")
    def _credential_matches_method(self) -> "ClockInRequest":
        if self.method == "pin" and not (self.pin and (self.worker_id or self.worker_no)):
            raise ValueError("worker_no (or worker_id) and pin are required when method='pin'")
        if self.method == "nfc" and not self.nfc_tag_id:
            raise ValueError("nfc_tag_id is required when method='nfc'")
        return self


class ClockOutRequest(BaseModel):
    gps: GpsCoordinates | None = None
    method: ClockMethod
    worker_id: str | None = None
    worker_no: str | None = None
    pin: str | None = None
    nfc_tag_id: str | None = None

    @model_validator(mode="after")
    def _credential_matches_method(self) -> "ClockOutRequest":
        if self.method == "pin" and not (self.pin and (self.worker_id or self.worker_no)):
            raise ValueError("worker_no (or worker_id) and pin are required when method='pin'")
        if self.method == "nfc" and not self.nfc_tag_id:
            raise ValueError("nfc_tag_id is required when method='nfc'")
        return self


class ClockInResponse(BaseModel):
    worker_id: str
    attendance_session_id: str
    clocked_in_at: datetime
    geofence_status: Literal["passed", "skipped"]
    matched_rostered_shift: bool
    state: str = "working"
    duplicate: bool = False  # true when this was a repeat tap: the first punch stands and nothing new was recorded


class ClockOutResponse(BaseModel):
    worker_id: str
    attendance_session_id: str
    clocked_in_at: datetime
    clocked_out_at: datetime
    duration_minutes: float
    state: str = "closed"
    duplicate: bool = False
    break_minutes: float = 0


class PunchRequest(ClockOutRequest):
    """Break start/end use the same credential shape as clock-out."""


class PunchResponse(BaseModel):
    worker_id: str
    attendance_session_id: str
    action: str
    state: str  # working | on_break | closed — the state AFTER this punch
    recorded_at: datetime  # the server's acknowledged time; if the kiosk never got this, nothing was recorded
    duplicate: bool = False
    break_minutes: float = 0


class UpcomingShift(BaseModel):
    shift_id: str
    role: str
    zone: str
    start_at: datetime
    end_at: datetime
    status: str


class SiteGeofenceRequest(BaseModel):
    site_id: str
    latitude: float
    longitude: float
    radius_meters: float


class WhoamiRequest(BaseModel):
    """Resolves a worker from a PIN/NFC tag without clocking in — the
    console's Kiosk page uses this to greet the worker and show their
    shifts before they decide to clock in/out.
    """

    method: ClockMethod
    worker_id: str | None = None
    worker_no: str | None = None
    pin: str | None = None
    nfc_tag_id: str | None = None

    @model_validator(mode="after")
    def _credential_matches_method(self) -> "WhoamiRequest":
        if self.method == "pin" and not (self.pin and (self.worker_id or self.worker_no)):
            raise ValueError("worker_no (or worker_id) and pin are required when method='pin'")
        if self.method == "nfc" and not self.nfc_tag_id:
            raise ValueError("nfc_tag_id is required when method='nfc'")
        return self


class WhoamiResponse(BaseModel):
    worker_id: str
    masked_identity: str  # what the kiosk may display on screen
    employment_type: str
    home_site: str
    has_open_session: bool
    state: str = "not_clocked_in"  # not_clocked_in | working | on_break
    allowed_actions: list[str] = []
    location_mode: str = "off"  # off | record | require — tells the kiosk whether to ask the browser for a position
    upcoming_shifts: list["UpcomingShift"] = []


class SiteAttendanceEntry(BaseModel):
    worker_id: str
    attendance_session_id: str
    clocked_in_at: datetime
    clocked_out_at: datetime | None
    matched_rostered_shift: bool
