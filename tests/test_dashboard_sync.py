from __future__ import annotations

import json

from privatelabbench.dashboard.schemas import SanitizedRunPayload
from privatelabbench.dashboard.store import DashboardStore
from privatelabbench.sync import sanitize_summary


def test_dashboard_health_endpoint():
    from fastapi.testclient import TestClient

    from privatelabbench import __version__
    from privatelabbench.dashboard.api import app

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "privatelabbench-dashboard",
        "version": __version__,
    }


def test_sanitize_summary_excludes_private_fields(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"ok": True}), encoding="utf-8")
    summary = {
        "project": "demo",
        "workflow": "predictions",
        "task_type": "regression",
        "n_samples": 10,
        "reported_metrics": {"mae": 0.1, "rmse": 0.2},
        "clean_metrics": {"mae": 0.05},
        "dataset_path": "/secret/lab.csv",
        "prediction_summary": {"raw": "do-not-sync"},
        "json_report": str(report),
        "privacy": "dp(epsilon=8.0, sensitivity=1.0)",
    }

    payload = sanitize_summary(summary, organization_id="org_1")

    assert payload.organization_id == "org_1"
    assert payload.project == "demo"
    assert payload.metrics == {"mae": 0.1, "rmse": 0.2}
    assert payload.privacy == {"summary": "dp(epsilon=8.0, sensitivity=1.0)"}
    dumped = payload.model_dump_json()
    assert "/secret/lab.csv" not in dumped
    assert "do-not-sync" not in dumped
    assert payload.artifacts[0].sha256 is not None


def test_dashboard_store_roundtrip(tmp_path):
    store = DashboardStore(tmp_path / "dashboard.db")
    payload = SanitizedRunPayload(
        organization_id="org_1",
        project="kinase-demo",
        workflow="predictions",
        task_type="regression",
        n_samples=20,
        metrics={"rmse": 0.4},
        privacy={"mode": "dp"},
    )

    created = store.create_run(payload)
    fetched = store.get_run(created.id)
    runs = store.list_runs(project="kinase-demo")
    events = store.list_audit_events(organization_id="org_1")

    assert fetched is not None
    assert fetched.project == "kinase-demo"
    assert fetched.metrics == {"rmse": 0.4}
    assert len(runs) == 1
    assert len(events) == 1
    assert events[0].event_type == "run_synced"
