"""UKG Ready (formerly Kronos Workforce Ready) client — Integration Spec §2.2.

REST, API-key auth (not OAuth2 — this is the concrete difference the spec
means by "UKG is not one API"). Mid-market tier (50-2,500 employees) —
"likely the more common product line among Tempo's mid-market target
customers" per the spec, so it's built alongside Pro WFM rather than
deferred.

Endpoint paths and field names below follow UKG Ready's general shape but
were NOT verified against a live tenant — same caveat as pro_wfm_client.py.
This client normalizes to the identical record shape pro_wfm_client.py
produces, so app/maestro/ukg/mapping.py and connector.py don't need to
know which product line they're talking to.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx

from app.maestro.base import PermanentError, RateLimited, TransientError, retry_with_backoff

PAGE_SIZE = 200
SOURCE_SYSTEM = "ukg_ready"


class UkgReadyClient:
    def __init__(self, tenant_subdomain: str, api_key: str, http_client: httpx.Client | None = None, sleep_fn=None):
        self.base_url = f"https://{tenant_subdomain}.ultipro.com/api/v2"
        self._api_key = api_key
        self._client = http_client or httpx.Client(base_url=self.base_url, timeout=30.0)
        self._sleep_fn = sleep_fn

    def _request(self, path: str, params: dict[str, Any]) -> httpx.Response:
        def do_request() -> httpx.Response:
            response = self._client.request("GET", path, headers={"Authorization": f"Bearer {self._api_key}"}, params=params)
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
        page_number = 1
        while True:
            params: dict[str, Any] = {"pageSize": PAGE_SIZE, "page": page_number}
            if modified_since is not None:
                params["updatedSince"] = modified_since
            page = self._request(path, params).json()
            records = page.get("results", page if isinstance(page, list) else [])
            for record in records:
                yield record
            if len(records) < PAGE_SIZE:
                return
            page_number += 1

    def list_employees(self, modified_since: str | None = None) -> Iterator[dict]:
        for record in self._paginate("/personnel/employees", modified_since):
            yield {
                "id": record.get("EmployeeNumber"),
                "active": record.get("Status") == "Active",
                "employment_category": record.get("EmployeeType"),
                "modified": record.get("UpdatedDate"),
            }

    def list_punches(self, modified_since: str | None = None) -> Iterator[dict]:
        for record in self._paginate("/time/punches", modified_since):
            yield {
                "id": record.get("PunchId"),
                "employee_id": record.get("EmployeeNumber"),
                "start": record.get("InPunchTime"),
                "end": record.get("OutPunchTime"),
                "approved": bool(record.get("IsApproved")),
                "modified": record.get("UpdatedDate"),
            }

    def list_shifts(self, modified_since: str | None = None) -> Iterator[dict]:
        for record in self._paginate("/scheduling/shifts", modified_since):
            yield {
                "id": record.get("ScheduleId"),
                "employee_id": record.get("EmployeeNumber"),
                "start": record.get("ShiftStart"),
                "end": record.get("ShiftEnd"),
                "location_code": record.get("HomeLocationCode"),
                "modified": record.get("UpdatedDate"),
            }

    def list_accruals(self, modified_since: str | None = None) -> Iterator[dict]:
        for record in self._paginate("/time/timeoff-requests", modified_since):
            yield {
                "id": record.get("RequestId"),
                "employee_id": record.get("EmployeeNumber"),
                "start": record.get("StartDate"),
                "end": record.get("EndDate"),
                "approved": record.get("ApprovalStatus") == "Approved",
                "modified": record.get("UpdatedDate"),
            }
