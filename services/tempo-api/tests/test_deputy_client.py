"""Tests the Deputy client's pagination and retry/backoff against a fake
transport — no real Deputy tenant involved (see client.py's docstring on
verifying the wire shape against a live one before production use).
"""
from __future__ import annotations

import httpx

from app.maestro.base import PermanentError
from app.maestro.deputy.client import PAGE_SIZE, DeputyClient


def _client_with_transport(handler) -> DeputyClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(base_url="https://acme.au.deputy.com/api/v1", transport=transport)
    return DeputyClient(install="acme", geo="au", bearer_token="tok", http_client=http_client, sleep_fn=lambda _: None)


def test_pagination_stops_on_short_page():
    pages = [[{"Id": i} for i in range(PAGE_SIZE)], [{"Id": i} for i in range(PAGE_SIZE, PAGE_SIZE + 3)]]
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        return httpx.Response(200, json=pages[len(calls) - 1])

    client = _client_with_transport(handler)
    records = list(client.list_employees())
    assert len(records) == PAGE_SIZE + 3
    assert len(calls) == 2
    assert calls[0]["skip"] == "0"
    assert calls[1]["skip"] == str(PAGE_SIZE)


def test_retries_on_429_then_succeeds():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json=[])

    client = _client_with_transport(handler)
    records = list(client.list_employees())
    assert records == []
    assert attempts["n"] == 2


def test_permanent_error_does_not_retry():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(404, text="not found")

    client = _client_with_transport(handler)
    try:
        list(client.list_employees())
        assert False, "expected PermanentError"
    except PermanentError:
        pass
    assert attempts["n"] == 1
