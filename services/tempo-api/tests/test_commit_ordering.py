"""A write must be committed BEFORE the response is sent: the next request has to see it, and a failing commit has to reach the caller as an error."""
from __future__ import annotations

from sqlalchemy import text

from app.main import app

from .conftest import _MaterialisingClient, context_header


class Spy:
    """ASGI wrapper: at the moment the response starts, look at the database through an independent connection."""

    def __init__(self, inner, probe):
        self.inner, self.probe, self.seen = inner, probe, None

    async def __call__(self, scope, receive, send):
        async def send2(message):
            if message["type"] == "http.response.start" and scope["method"] == "PUT":
                self.seen = self.probe()
            await send(message)
        await self.inner(scope, receive, send2)


def test_a_write_is_visible_to_other_connections_before_the_response_is_sent(client):
    from .test_imports import seed
    seed(client)

    def probe():
        with client.session_local() as s:   # a separate (owner) connection, like the next request would be
            return s.execute(text("SELECT source FROM site_forecast_preference WHERE site_id = 'site_mel_01'")).scalar()
    spy = Spy(app, probe)
    c = _MaterialisingClient(spy)
    c.session_local, c.app_session_local = client.session_local, client.app_session_local
    h = context_header(roles=["tenant_admin"], user_id="usr_admin", site_ids=["site_mel_01", "site_syd_01"])
    with c:
        r = c.put("/v1/sites/site_mel_01/forecast-source", json={"source": "supplied"}, headers=h)
    assert r.status_code == 200
    assert spy.seen == "supplied", "the write was not committed when the response started"
