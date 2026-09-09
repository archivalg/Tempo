"""Native capture contracts — Business Spec §4/§5 (Standalone mode)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator

ClockMethod = Literal["pin", "nfc"]


class GpsCoordinates(BaseModel):
    latitude: float
    longitude: float


class CredentialEnrollRequest(BaseModel):
    worker_id: str
    pin: str | None = None
    nfc_tag_id: str | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "CredentialEnrollRequest":
        if not self.pin and not self.nfc_tag_id:
            raise ValueError("at least one of pin or nfc_tag_id is required")
        return self


class CredentialEnrollResponse(BaseModel):
    worker_id: str
    has_pin: bool
    has_nfc: bool


class ClockInRequest(BaseModel):
    site_id: str
    method: ClockMethod
    pin: str | None = None
    nfc_tag_id: str | None = None
    gps: GpsCoordinates | None = None

    @model_validator(mode="after")
    def _credential_matches_method(self) -> "ClockInRequest":
        if self.method == "pin" and not self.pin:
            raise ValueError("pin is required when method='pin'")
        if self.method == "nfc" and not self.nfc_tag_id:
            raise ValueError("nfc_tag_id is required when method='nfc'")
        return self


class ClockOutRequest(BaseModel):
    method: ClockMethod
    pin: str | None = None
    nfc_tag_id: str | None = None

    @model_validator(mode="after")
    def _credential_matches_method(self) -> "ClockOutRequest":
        if self.method == "pin" and not self.pin:
            raise ValueError("pin is required when method='pin'")
        if self.method == "nfc" and not self.nfc_tag_id:
            raise ValueError("nfc_tag_id is required when method='nfc'")
        return self


class ClockInResponse(BaseModel):
    worker_id: str
    attendance_session_id: str
    clocked_in_at: datetime
    geofence_status: Literal["passed", "skipped"]
    matched_rostered_shift: bool


class ClockOutResponse(BaseModel):
    worker_id: str
    attendance_session_id: str
    clocked_in_at: datetime
    clocked_out_at: datetime
    duration_minutes: float


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
    pin: str | None = None
    nfc_tag_id: str | None = None

    @model_validator(mode="after")
    def _credential_matches_method(self) -> "WhoamiRequest":
        if self.method == "pin" and not self.pin:
            raise ValueError("pin is required when method='pin'")
        if self.method == "nfc" and not self.nfc_tag_id:
            raise ValueError("nfc_tag_id is required when method='nfc'")
        return self


class WhoamiResponse(BaseModel):
    worker_id: str
    employment_type: str
    home_site: str
    has_open_session: bool


class SiteAttendanceEntry(BaseModel):
    worker_id: str
    attendance_session_id: str
    clocked_in_at: datetime
    clocked_out_at: datetime | None
    matched_rostered_shift: bool
