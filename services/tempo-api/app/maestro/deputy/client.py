"""Deputy REST client — Integration Spec §2.1.

Auth: bearer token (OAuth2), per-installation subdomain endpoint
(https://{install}.{geo}.deputy.com/api/v1/...). Pagination: hard cap of
500 records/response, no override — this client always pages.

The exact per-resource pagination query params below (`max`/`skip`) follow
Deputy's general v1 REST convention but have NOT been verified against a
live Deputy tenant — no Deputy sandbox was available while building this.
Confirm the literal param names/response envelope against Deputy's current
API docs before pointing this at production, and update _fetch_page's
request shape if they differ; everything downstream (mapping, ingestion,
retry/backoff) is unaffected by that detail.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx

from app.maestro.base import PermanentError, RateLimited, TransientError, retry_with_backoff

PAGE_SIZE = 500  # §2.1: hard cap, no override


class DeputyClient:
    def __init__(
        self,
        install: str,
        geo: str,
        bearer_token: str,
        http_client: httpx.Client | None = None,
        sleep_fn=None,
    ):
        self.base_url = f"https://{install}.{geo}.deputy.com/api/v1"
        self._token = bearer_token
        self._client = http_client or httpx.Client(base_url=self.base_url, timeout=30.0)
        self._sleep_fn = sleep_fn

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        def do_request() -> httpx.Response:
            response = self._client.request(
                method, path, headers={"Authorization": f"Bearer {self._token}"}, **kwargs
            )
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                raise RateLimited(float(retry_after) if retry_after else None)
            if response.status_code >= 500:
                raise TransientError(f"{method} {path} -> {response.status_code}")
            if response.status_code >= 400:
                raise PermanentError(f"{method} {path} -> {response.status_code}: {response.text}")
            return response

        kwargs_retry = {"sleep_fn": self._sleep_fn} if self._sleep_fn is not None else {}
        return retry_with_backoff(do_request, **kwargs_retry)

    def _paginate(self, resource: str, modified_since: str | None) -> Iterator[dict]:
        skip = 0
        while True:
            params: dict[str, Any] = {"max": PAGE_SIZE, "skip": skip}
            if modified_since is not None:
                params["modifiedSince"] = modified_since
            response = self._request("GET", f"/resource/{resource}", params=params)
            page = response.json()
            records = page if isinstance(page, list) else page.get("data", [])
            for record in records:
                yield record
            if len(records) < PAGE_SIZE:
                return
            skip += PAGE_SIZE

    def list_employees(self, modified_since: str | None = None) -> Iterator[dict]:
        yield from self._paginate("Employee", modified_since)

    def list_timesheets(self, modified_since: str | None = None) -> Iterator[dict]:
        yield from self._paginate("Timesheet", modified_since)

    def list_rosters(self, modified_since: str | None = None) -> Iterator[dict]:
        yield from self._paginate("Roster", modified_since)

    def list_leave(self, modified_since: str | None = None) -> Iterator[dict]:
        yield from self._paginate("Leave", modified_since)
