"""Pagination/retry tests for both UKG product-line clients, plus a check
that they normalize to the identical record shape mapping.py expects —
the actual proof of "one connector, per-product-line pluggable client."
"""
from __future__ import annotations

import httpx

from app.maestro.base import PermanentError
from app.maestro.ukg.pro_wfm_client import PAGE_SIZE as WFM_PAGE_SIZE, UkgProWfmClient
from app.maestro.ukg.ready_client import PAGE_SIZE as READY_PAGE_SIZE, UkgReadyClient

NORMALIZED_EMPLOYEE_KEYS = {"id", "active", "employment_category", "modified"}


def _wfm_client(handler) -> UkgProWfmClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(base_url="https://acme.workforcedimensions.com/api/v1", transport=transport)
    return UkgProWfmClient(tenant_subdomain="acme", bearer_token="tok", http_client=http_client, sleep_fn=lambda _: None)


def _ready_client(handler) -> UkgReadyClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(base_url="https://acme.ultipro.com/api/v2", transport=transport)
    return UkgReadyClient(tenant_subdomain="acme", api_key="key", http_client=http_client, sleep_fn=lambda _: None)


def test_pro_wfm_pagination_and_normalization():
    pages = [
        [{"employeeId": str(i), "employmentStatus": "Active"} for i in range(WFM_PAGE_SIZE)],
        [{"employeeId": "last", "employmentStatus": "Active"}],
    ]
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        return httpx.Response(200, json={"items": pages[len(calls) - 1]})

    client = _wfm_client(handler)
    records = list(client.list_employees())
    assert len(records) == WFM_PAGE_SIZE + 1
    assert len(calls) == 2
    assert set(records[0].keys()) == NORMALIZED_EMPLOYEE_KEYS


def test_ready_pagination_and_normalization():
    pages = [
        [{"EmployeeNumber": str(i), "Status": "Active"} for i in range(READY_PAGE_SIZE)],
        [{"EmployeeNumber": "last", "Status": "Active"}],
    ]
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        return httpx.Response(200, json={"results": pages[len(calls) - 1]})

    client = _ready_client(handler)
    records = list(client.list_employees())
    assert len(records) == READY_PAGE_SIZE + 1
    assert len(calls) == 2
    assert set(records[0].keys()) == NORMALIZED_EMPLOYEE_KEYS


def test_ready_client_permanent_error_does_not_retry():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(401, text="unauthorized")

    client = _ready_client(handler)
    try:
        list(client.list_employees())
        assert False, "expected PermanentError"
    except PermanentError:
        pass
    assert attempts["n"] == 1
