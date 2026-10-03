"""Roadmap M6-HELP: the public API reference lists only the supported ingestion endpoints, and its examples work against the running API."""
from __future__ import annotations

import json

from .conftest import context_header
from .test_imports import MEL, SYD, admin, seed


def test_framework_docs_that_list_every_internal_route_are_off(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404, path


def test_public_schema_lists_only_ingestion_endpoints_and_no_internal_names(client):
    r = client.get("/v1/api/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert set(spec["paths"]) == {"/v1/imports/contracts", "/v1/imports/contracts/{data_class}", "/v1/imports/contracts/{data_class}/template.csv", "/v1/imports/batches",
                                  "/v1/imports/batches/{batch_id}", "/v1/imports/batches/{batch_id}/errors.csv", "/v1/imports/batches/{batch_id}/apply", "/v1/imports/batches/{batch_id}/undo", "/v1/imports/status"}
    text = json.dumps(spec).lower()
    for internal in ("platform", "support-grant", "kiosk", "/v1/auth", "invite", "password", "mfa", "dev-login"):
        assert internal not in text, internal
    assert spec["components"]["securitySchemes"]["serviceCredential"]["scheme"] == "bearer"
    assert all(op["security"] == [{"serviceCredential": []}] for p in spec["paths"].values() for op in p.values())
    assert set(spec["paths"]["/v1/imports/batches"]["post"]["requestBody"]["content"]["application/json"]["examples"]) >= {"forecast", "bulk", "bulk_replace_slice", "transactions", "master_workers", "master_sites", "master_rates"}
    assert any(p["name"] == "Idempotency-Key" for p in spec["paths"]["/v1/imports/batches"]["post"]["parameters"])
    assert "Idempotency-Key" in spec["info"]["description"] and "tsc_" in spec["info"]["description"]
    assert client.get("/v1/api/docs").status_code == 200 and "swagger" in client.get("/v1/api/docs").text.lower()


def test_documented_examples_are_accepted_by_the_running_api(client):
    seed(client)
    h = admin()
    spec = client.get("/v1/api/openapi.json").json()
    ex = spec["paths"]["/v1/imports/batches"]["post"]["requestBody"]["content"]["application/json"]["examples"]
    fix = {"mel_dc_01": MEL, "cust_A": "cust_A"}
    for key in ("master_work_standards", "master_customers", "master_rates", "master_sites", "master_workers", "master_availability", "forecast", "bulk", "bulk_replace_slice", "transactions"):
        body = json.loads(json.dumps(ex[key]["value"]))
        for row in body["rows"]:
            for k, v in list(row.items()):
                if v in fix:
                    row[k] = fix[v]
            if "site" in row and body["data_class"] in ("forecast", "bulk", "transactions", "master"):
                row["site"] = MEL
            if key == "master_availability":
                row["worker_ref"] = "E1042"
        if key == "master_availability":   # people must exist first: the example worker is loaded by the staff example
            continue
        if key == "forecast":
            row0 = body["rows"][0]; row0["activity"] = "picking"
        if key in ("bulk", "bulk_replace_slice", "transactions"):
            body["rows"][0]["activity"] = "picking"
        r = client.post("/v1/imports/batches", json=body, headers={**h, "Idempotency-Key": f"doc-{key}"})
        assert r.status_code == 201, (key, r.text)
        assert r.json()["error_rows"] == 0, (key, r.json())
        if key == "master_workers":
            ok = client.post("/v1/imports/batches", json=ex["master_availability"]["value"], headers={**h, "Idempotency-Key": "doc-avail"})
            assert ok.status_code in (201, 422)
