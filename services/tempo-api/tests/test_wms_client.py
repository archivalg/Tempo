"""Pagination/retry tests for the WMS client — same fake-transport
approach as the Deputy/UKG client tests, no real WMS involved.
"""
from __future__ import annotations

import httpx

from app.maestro.base import PermanentError
from app.maestro.wms.client import PAGE_SIZE, WmsClient


def _client(handler) -> WmsClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(base_url="https://wms.example.com/api", transport=transport)
    return WmsClient(base_url="https://wms.example.com/api", bearer_token="tok", http_client=http_client, sleep_fn=lambda _: None)


def test_pagination_stops_on_short_page():
    pages = [[{"id": str(i)} for i in range(PAGE_SIZE)], [{"id": "last"}]]
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        return httpx.Response(200, json={"items": pages[len(calls) - 1]})

    records = list(_client(handler).list_backlog_snapshots())
    assert len(records) == PAGE_SIZE + 1
    assert len(calls) == 2


def test_permanent_error_does_not_retry():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(403, text="forbidden")

    try:
        list(_client(handler).list_backlog_snapshots())
        assert False, "expected PermanentError"
    except PermanentError:
        pass
    assert attempts["n"] == 1
