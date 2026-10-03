"""The supported public API reference (roadmap M6-HELP): a filtered OpenAPI schema plus a Swagger UI, both on the API origin.

Only an allow-list of endpoints (data ingestion with service credentials) is described. Internal routes (platform, auth, admin, kiosk, planning)
are never listed. Schemas not reachable from the listed endpoints are dropped. Examples come from the data contracts, so they cannot drift from the validators.
"""
from __future__ import annotations

import copy
import re

from fastapi import APIRouter, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from app.imports.contracts import CONTRACTS, CONTRACT_VERSION, MAX_ROWS

router = APIRouter(prefix="/api", tags=["api-docs"], include_in_schema=False)

PUBLIC = [("get", "/v1/imports/contracts"), ("get", "/v1/imports/contracts/{data_class}"), ("get", "/v1/imports/contracts/{data_class}/template.csv"),
          ("post", "/v1/imports/batches"), ("get", "/v1/imports/batches"), ("get", "/v1/imports/batches/{batch_id}"), ("get", "/v1/imports/batches/{batch_id}/errors.csv"),
          ("post", "/v1/imports/batches/{batch_id}/apply"), ("post", "/v1/imports/batches/{batch_id}/undo"), ("get", "/v1/imports/status")]

INTRO = f"""Load master data, forecasts and workload into Tempo from your own systems.

**Authentication.** Create a service credential in Tempo (Data → API credentials). Send it as `Authorization: Bearer tsc_…`. A credential can only import data, is scoped to the sites you choose, can be rotated or revoked, and its secret is shown once.

**Idempotency.** Send an `Idempotency-Key` header on `POST /v1/imports/batches`. Repeating a request with the same key (or the same content) returns the original receipt instead of loading twice.

**Corrections.** Workload events carry an `action` (`create`, `correct`, `cancel`) and an increasing `revision`; a lower revision than the one held is ignored. Totals are upserted per site, activity and period; `replace_slice` replaces a stated date range.

**Time.** Timestamps are ISO 8601 with an offset (`2026-10-05T09:00:00+11:00`) or site-local (`2026-10-05 09:00`); times that do not exist or are ambiguous across a daylight-saving change are rejected with instructions.

**Limits.** At most {MAX_ROWS:,} rows per request; split larger loads. Contract version {CONTRACT_VERSION}. Rows are validated individually and rejected rows come back with reasons; nothing is applied unless you ask (`apply: true`) or call apply on the receipt.
"""


def _refs(node, found: set[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                found.add(v.rsplit("/", 1)[-1])
            else:
                _refs(v, found)
    elif isinstance(node, list):
        for v in node:
            _refs(v, found)


def _examples() -> dict:
    out = {}
    for (dc, ent), c in CONTRACTS.items():
        row = {f.name: f.example for f in c.fields}
        body = {"data_class": dc, **({"entity": ent} if ent else {}), "rows": [row], "apply": False}
        opts = {f.name: f.example for f in c.batch_options if f.required}
        if opts:
            body["options"] = opts
        out[f"{dc}{'_' + ent if ent else ''}"] = {"summary": c.title, "value": body}
        if dc == "bulk":   # a second, fuller example: replace a stated range and check the total
            full = copy.deepcopy(body)
            full["options"] = {"mode": "replace_slice", "slice_start": "2026-10-05", "slice_end": "2026-10-05", "control_total": row["units"]}
            out["bulk_replace_slice"] = {"summary": "Workload totals — replace a date range with a control total", "value": full}
    return out


def build_public_schema(full: dict) -> dict:
    paths = {}
    for method, path in PUBLIC:
        op = copy.deepcopy(full["paths"][path][method])
        op["security"] = [{"serviceCredential": []}]
        paths.setdefault(path, {})[method] = op
    batch_post = paths["/v1/imports/batches"]["post"]
    batch_post.setdefault("requestBody", {}).setdefault("content", {}).setdefault("application/json", {})["examples"] = _examples()
    batch_post["parameters"] = [p for p in batch_post.get("parameters", []) if p.get("name", "").lower() != "idempotency-key"] + [
        {"name": "Idempotency-Key", "in": "header", "required": False, "schema": {"type": "string"}, "description": "A unique key per logical load. A retry with the same key returns the original receipt."}]
    needed: set[str] = set()
    _refs(paths, needed)
    comps = full.get("components", {}).get("schemas", {})
    keep: dict = {}
    todo = list(needed)
    while todo:
        n = todo.pop()
        if n in keep or n not in comps:
            continue
        keep[n] = comps[n]
        more: set[str] = set()
        _refs(comps[n], more)
        todo += list(more - set(keep))
    return {"openapi": full["openapi"], "info": {"title": "Tempo Data API", "version": CONTRACT_VERSION, "description": INTRO},
            "servers": [{"url": "/"}], "paths": paths,
            "components": {"schemas": keep, "securitySchemes": {"serviceCredential": {"type": "http", "scheme": "bearer", "description": "A Tempo service credential (starts with tsc_)."}}}}


@router.get("/openapi.json")
def public_openapi(request: Request) -> JSONResponse:
    from fastapi.openapi.utils import get_openapi
    app = request.app
    if not hasattr(app.state, "public_schema"):
        full = get_openapi(title="internal", version="0", routes=app.routes)
        app.state.public_schema = build_public_schema(full)
    return JSONResponse(app.state.public_schema, headers={"Content-Disposition": 'inline; filename="tempo-data-api-openapi.json"'})


@router.get("/docs", response_class=HTMLResponse)
def public_docs() -> HTMLResponse:
    return get_swagger_ui_html(openapi_url="/v1/api/openapi.json", title="Tempo Data API")
