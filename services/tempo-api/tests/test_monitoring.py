"""Model monitoring — §15.2, Phase F. Checks the property that makes this
model real: drift is flagged only when a run_type's recent runs actually
degrade against its older ones by more than policy's threshold, computed
from real stored run history, not a synthetic score.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.monitoring import check_drift, compute_model_monitoring
from app.models.runs import EventRecord, OptimisationRun

from .conftest import context_header

BASE_TIME = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _run(run_id: str, *, feasibility: str, confidence: float, hours_offset: int, model_version: str = "1.0.0") -> OptimisationRun:
    return OptimisationRun(
        run_id=run_id, tenant_id="ten_test", run_type="named_roster", status="completed",
        request={}, snapshot_id="snap", model_version=model_version,
        explanation={"feasibility": feasibility, "confidence": {"score": confidence}},
        result={}, created_at=BASE_TIME + timedelta(hours=hours_offset),
    )


def test_compute_model_monitoring_reports_solver_gap_and_confidence(client):
    with client.session_local() as db:
        db.add(_run("r0", feasibility="feasible", confidence=0.9, hours_offset=0))
        db.add(_run("r1", feasibility="infeasible", confidence=0.5, hours_offset=1))
        db.commit()
        metrics = compute_model_monitoring(db, "ten_test")

    assert metrics["named_roster"]["run_count"] == 2
    assert metrics["named_roster"]["solver_gap_rate"] == 0.5
    assert metrics["named_roster"]["avg_confidence"] == 0.7


def test_check_drift_flags_a_confidence_drop_and_publishes_event(client):
    with client.session_local() as db:
        for i in range(4):
            db.add(_run(f"old_{i}", feasibility="feasible", confidence=0.9, hours_offset=i))
        for i in range(4):
            db.add(_run(f"new_{i}", feasibility="feasible", confidence=0.5, hours_offset=24 + i))
        db.commit()

        signals = check_drift(db, "ten_test")
        events = db.query(EventRecord).filter(
            EventRecord.tenant_id == "ten_test", EventRecord.event_type == "model.drift.detected"
        ).all()

    assert len(signals) == 1
    assert signals[0]["run_type"] == "named_roster"
    assert signals[0]["metric"] == "confidence"
    assert len(events) == 1


def test_check_drift_reports_nothing_below_threshold(client):
    with client.session_local() as db:
        for i in range(4):
            db.add(_run(f"old_{i}", feasibility="feasible", confidence=0.85, hours_offset=i))
        for i in range(4):
            db.add(_run(f"new_{i}", feasibility="feasible", confidence=0.82, hours_offset=24 + i))
        db.commit()
        signals = check_drift(db, "ten_test")

    assert signals == []


def test_monitoring_endpoint_requires_labour_read(client):
    response = client.get("/v1/monitoring/models", headers=context_header(roles=["integration_restricted"]))
    assert response.status_code == 403
    assert response.json()["error_code"] == "TEMPO-AUTH-002"


def test_drift_check_endpoint_requires_labour_configure(client):
    response = client.post("/v1/monitoring/models/drift-check", headers=context_header(roles=["analyst"]))
    assert response.status_code == 403
    assert response.json()["error_code"] == "TEMPO-AUTH-002"


def test_monitoring_endpoint_returns_computed_metrics(client):
    with client.session_local() as db:
        db.add(_run("r0", feasibility="feasible", confidence=0.9, hours_offset=0))
        db.commit()

    response = client.get("/v1/monitoring/models", headers=context_header())
    assert response.status_code == 200
    assert "named_roster" in response.json()["models"]
