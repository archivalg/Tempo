"""Generic WMS REST client — Integration Spec §7.2's "Active tasks /
backlog" domain (target freshness 1-5 minutes where intraday reallocation
is enabled).

Unlike Deputy/UKG, the spec doesn't name a specific WMS vendor — warehouse
management systems vary widely (Manhattan, Blue Yonder, SAP EWM, Made4Net,
and many bespoke ones), so there's no single API to match. This client is
therefore explicitly illustrative: bearer-token REST with the same
pagination/retry shape as every other connector in app/maestro/, and a
generic `/backlog` resource returning per-zone snapshots. Adapt the
endpoint path and field names to whichever WMS a real tenant runs — the
canonical mapping (mapping.py) and everything downstream is insulated from
that by the normalized record shape this client returns, the same
insulation pattern app/maestro/ukg/ established across two real product
lines.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx

from app.maestro.base import PermanentError, RateLimited, TransientError, retry_with_backoff

PAGE_SIZE = 500
SOURCE_SYSTEM = "wms"


class WmsClient:
    def __init__(self, base_url: str, bearer_token: str, http_client: httpx.Client | None = None, sleep_fn=None):
        self.base_url = base_url
        self._token = bearer_token
        self._client = http_client or httpx.Client(base_url=base_url, timeout=30.0)
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

    def list_backlog_snapshots(self, modified_since: str | None = None) -> Iterator[dict]:
        yield from self._paginate("/backlog", modified_since)
