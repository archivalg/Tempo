from .conftest import context_header


def test_unknown_capability_is_not_ready(client):
    response = client.get(
        "/v1/data-readiness", params={"capability": "unknown.capability"}, headers=context_header()
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_ready"
    assert "unknown capability" in body["blocking_issues"][0]


def test_known_capability_with_no_data_reports_not_ready_domains(client):
    response = client.get(
        "/v1/data-readiness", params={"capability": "optimize.roster"}, headers=context_header()
    )
    body = response.json()
    assert body["status"] in {"not_ready", "ready_with_warnings"}
    domains = {d["domain"] for d in body["required_domains"]}
    assert domains == {"worker", "availability", "skill_certification"}
    assert all(d["status"] == "not_ready" for d in body["required_domains"])
