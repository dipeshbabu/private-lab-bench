from __future__ import annotations

import json

from privatelabbench.dashboard.schemas import ArtifactMetadata, SanitizedRunPayload
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


def test_dashboard_home_renders_sanitized_runs(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from privatelabbench.dashboard.api import app

    monkeypatch.delenv("PRIVATELABBENCH_DASHBOARD_API_KEY", raising=False)
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_DB", str(tmp_path / "dashboard.db"))
    store = DashboardStore(tmp_path / "dashboard.db")
    created = store.create_run(
        SanitizedRunPayload(
            organization_id="org_1",
            run_id="source-run-1",
            benchmark_id="kinase-private-v1",
            benchmark_version="2026.05",
            project="kinase-demo",
            workflow="predictions",
            task_type="regression",
            n_samples=20,
            metrics={"rmse": 0.4},
            privacy={"mode": "dp"},
            metadata={"dataset_path": "/secret/lab.csv"},
        )
    )

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "PrivateLabBench Dashboard" in response.text
    assert "kinase-private-v1@2026.05" in response.text
    assert "kinase-demo" in response.text
    assert "rmse" in response.text
    assert "0.4" in response.text
    assert f"/runs/{created.id}" in response.text
    assert "/secret/lab.csv" not in response.text


def test_dashboard_run_detail_renders_sanitized_metadata(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from privatelabbench.dashboard.api import app

    monkeypatch.delenv("PRIVATELABBENCH_DASHBOARD_API_KEY", raising=False)
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_DB", str(tmp_path / "dashboard.db"))
    store = DashboardStore(tmp_path / "dashboard.db")
    created = store.create_run(
        SanitizedRunPayload(
            organization_id="org_1",
            run_id="source-run-1",
            benchmark_id="kinase-private-v1",
            benchmark_version="2026.05",
            benchmark_suite="molecular-property",
            domain="molecules",
            project="kinase-demo",
            workflow="predictions",
            task_type="regression",
            n_samples=20,
            metrics={"rmse": 0.4},
            privacy={"summary": "DP-style metric noise applied."},
            artifacts=[
                ArtifactMetadata(
                    name="kinase_prediction_eval.json",
                    kind="json",
                    sha256="abc123",
                )
            ],
            metadata={"release": "pilot", "dataset_path": "/secret/lab.csv"},
        )
    )

    response = TestClient(app).get(f"/runs/{created.id}")

    assert response.status_code == 200
    assert f"Run {created.id}" in response.text
    assert "source-run-1" in response.text
    assert "kinase-private-v1" in response.text
    assert "molecular-property" in response.text
    assert "kinase-demo" in response.text
    assert "rmse" in response.text
    assert "DP-style metric noise applied." in response.text
    assert "kinase_prediction_eval.json" in response.text
    assert "abc123" in response.text
    assert "pilot" in response.text
    assert "run_synced" in response.text
    assert "/secret/lab.csv" not in response.text


def test_dashboard_home_accepts_api_key_query(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from privatelabbench.dashboard.api import app

    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_API_KEY", "dashboard-secret")
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_DB", str(tmp_path / "dashboard.db"))
    client = TestClient(app)

    assert client.get("/").status_code == 401
    assert client.get("/?api_key=dashboard-secret").status_code == 200


def test_dashboard_run_detail_accepts_api_key_query(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from privatelabbench.dashboard.api import app

    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_API_KEY", "dashboard-secret")
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_DB", str(tmp_path / "dashboard.db"))
    created = DashboardStore(tmp_path / "dashboard.db").create_run(
        SanitizedRunPayload(
            organization_id="org_1",
            project="kinase-demo",
            workflow="predictions",
            metrics={"rmse": 0.4},
        )
    )
    client = TestClient(app)

    assert client.get(f"/runs/{created.id}").status_code == 401
    assert client.get(f"/runs/{created.id}?api_key=dashboard-secret").status_code == 200


def test_sanitize_summary_excludes_private_fields(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"ok": True}), encoding="utf-8")
    summary = {
        "project": "demo",
        "workflow": "predictions",
        "task_type": "regression",
        "n_samples": 10,
        "reported_metrics": {"mae": 0.1, "rmse": 0.2},
        "run_id": "source-run-1",
        "benchmark_id": "kinase-private-v1",
        "benchmark_version": "2026.05",
        "benchmark_suite": "molecular-property",
        "domain": "molecules",
        "clean_metrics": {"mae": 0.05},
        "dataset_path": "/secret/lab.csv",
        "prediction_summary": {"raw": "do-not-sync"},
        "json_report": str(report),
        "privacy": "dp(epsilon=8.0, sensitivity=1.0)",
    }

    payload = sanitize_summary(summary, organization_id="org_1")

    assert payload.organization_id == "org_1"
    assert payload.project == "demo"
    assert payload.run_id == "source-run-1"
    assert payload.benchmark_id == "kinase-private-v1"
    assert payload.benchmark_version == "2026.05"
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
        run_id="source-run-1",
        benchmark_id="kinase-private-v1",
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
    assert fetched.source_run_id == "source-run-1"
    assert fetched.benchmark_id == "kinase-private-v1"
    assert fetched.metrics == {"rmse": 0.4}
    assert len(runs) == 1
    assert len(store.list_runs(benchmark_id="kinase-private-v1")) == 1
    assert len(events) == 1
    assert events[0].event_type == "run_synced"
    assert events[0].payload["benchmark_id"] == "kinase-private-v1"


def test_dashboard_store_leaderboard_filters_nonpublishable_runs(tmp_path):
    store = DashboardStore(tmp_path / "dashboard.db")
    store.create_run(
        SanitizedRunPayload(
            organization_id="org_1",
            run_id="source-run-1",
            benchmark_id="kinase-private-v1",
            project="candidate-a",
            workflow="predictions",
            n_samples=20,
            metrics={"rmse": 0.2},
            metadata={"privacy_gate_publishable": True, "privacy_gate_status": "pass"},
        )
    )
    store.create_run(
        SanitizedRunPayload(
            organization_id="org_2",
            run_id="source-run-2",
            benchmark_id="kinase-private-v1",
            project="candidate-b",
            workflow="predictions",
            n_samples=20,
            metrics={"rmse": 0.1},
            metadata={"privacy_gate_publishable": False, "privacy_gate_status": "fail"},
        )
    )

    publishable = store.leaderboard(benchmark_id="kinase-private-v1", metric="rmse")
    all_entries = store.leaderboard(
        benchmark_id="kinase-private-v1",
        metric="rmse",
        require_publishable=False,
    )

    assert [entry.project for entry in publishable] == ["candidate-a"]
    assert [entry.project for entry in all_entries] == ["candidate-b", "candidate-a"]
    assert all_entries[0].rank == 1


def test_dashboard_leaderboard_endpoint_returns_sanitized_entries(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from privatelabbench.dashboard.api import app

    monkeypatch.delenv("PRIVATELABBENCH_DASHBOARD_API_KEY", raising=False)
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_DB", str(tmp_path / "dashboard.db"))
    DashboardStore(tmp_path / "dashboard.db").create_run(
        SanitizedRunPayload(
            organization_id="org_1",
            run_id="source-run-1",
            benchmark_id="kinase-private-v1",
            project="candidate-a",
            workflow="predictions",
            n_samples=20,
            metrics={"rmse": 0.2},
            metadata={"privacy_gate_publishable": True, "dataset_path": "/secret/lab.csv"},
        )
    )

    api_response = TestClient(app).get("/v1/leaderboards/kinase-private-v1?metric=rmse")
    html_response = TestClient(app).get("/leaderboards/kinase-private-v1?metric=rmse")

    assert api_response.status_code == 200
    assert api_response.json()[0]["project"] == "candidate-a"
    assert html_response.status_code == 200
    assert "Leaderboard kinase-private-v1" in html_response.text
    assert "candidate-a" in html_response.text
    assert "/secret/lab.csv" not in html_response.text
