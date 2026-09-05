"""UKG Pro WFM (formerly UKG Dimensions) client — Integration Spec §2.2.

REST, OAuth 2.0 with tenant API keys, webhook subscriptions available.
Covers punches, shifts, schedules, accruals, attendance — "closest fit to
Tempo's needs" per the spec, so this is the UKG product line built first
(before UKG Ready) here.

Endpoint paths and field names below (`/timekeeping/punches`, `employeeId`,
etc.) follow UKG Pro WFM's general shape but were NOT verified against a
live tenant — no sandbox was available. As with the Deputy client, the
*behaviour* (auth header, pagination, retry) is real and tested; the
literal wire format needs a sandbox check before production use.

Every list_* method yields records already normalized to the shape
app/maestro/ukg/mapping.py expects — vendor field-name differences are
absorbed here, at the boundary, so UKG Ready's client (same normalized
shape, different internal field names) can share one mapping module.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx

from app.maestro.base import PermanentError, RateLimited, TransientError, retry_with_backoff

PAGE_SIZE = 200
SOURCE_SYSTEM = "ukg_pro_wfm"


class UkgProWfmClient:
    def __init__(self, tenant_subdomain: str, bearer_token: str, http_client: httpx.Client | None = None, sleep_fn=None):
        self.base_url = f"https://{tenant_subdomain}.workforcedimensions.com/api/v1"
        self._token = bearer_token
        self._client = http_client or httpx.Client(base_url=self.base_url, timeout=30.0)
        self._sleep_fn = sleep_fn

    def _request(self, path: str, params: dict[str, Any]) -> httpx.Response:
        def do_request() -> httpx.Response:
            response = self._client.request("GET", path, headers={"Authorization": f"Bearer {self._token}"}, params=params)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                raise RateLimited(float(retry_after) if retry_after else None)
            if response.status_code >= 500:
                raise TransientError(f"GET {path} -> {response.status_code}")
            if response.status_code >= 400:
                raise PermanentError(f"GET {path} -> {response.status_code}: {response.text}")
            return response

        kwargs = {"sleep_fn": self._sleep_fn} if self._sleep_fn is not None else {}
        return retry_with_backoff(do_request, **kwargs)

    def _paginate(self, path: str, modified_since: str | None) -> Iterator[dict]:
        offset = 0
        while True:
            params: dict[str, Any] = {"limit": PAGE_SIZE, "offset": offset}
            if modified_since is not None:
                params["modifiedSince"] = modified_since
            page = self._request(path, params).json()
            records = page.get("items", page if isinstance(page, list) else [])
            for record in records:
                yield record
            if len(records) < PAGE_SIZE:
                return
            offset += PAGE_SIZE

    def list_employees(self, modified_since: str | None = None) -> Iterator[dict]:
        for record in self._paginate("/employees", modified_since):
            yield {
                "id": record.get("employeeId"),
                "active": record.get("employmentStatus") == "Active",
                "employment_category": record.get("workerCategory"),
                "modified": record.get("lastModifiedTimestamp"),
            }

    def list_punches(self, modified_since: str | None = None) -> Iterator[dict]:
        for record in self._paginate("/timekeeping/punches", modified_since):
            yield {
                "id": record.get("punchId"),
                "employee_id": record.get("employeeId"),
                "start": record.get("punchInTime"),
                "end": record.get("punchOutTime"),
                "approved": record.get("approvalStatus") == "Approved",
                "modified": record.get("lastModifiedTimestamp"),
            }

    def list_shifts(self, modified_since: str | None = None) -> Iterator[dict]:
        for record in self._paginate("/scheduling/shifts", modified_since):
            yield {
                "id": record.get("shiftId"),
                "employee_id": record.get("employeeId"),
                "start": record.get("startDateTime"),
                "end": record.get("endDateTime"),
                "location_code": record.get("scheduleGroupId"),
                "modified": record.get("lastModifiedTimestamp"),
            }

    def list_accruals(self, modified_since: str | None = None) -> Iterator[dict]:
        for record in self._paginate("/accruals/leave", modified_since):
            yield {
                "id": record.get("leaveRequestId"),
                "employee_id": record.get("employeeId"),
                "start": record.get("startDate"),
                "end": record.get("endDate"),
                "approved": record.get("status") == "Approved",
                "modified": record.get("lastModifiedTimestamp"),
            }
