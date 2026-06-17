from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from privatelabbench.dashboard.schemas import ArtifactMetadata, SanitizedEvidencePayload, SanitizedRunPayload
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


def test_dashboard_ready_and_metrics_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from privatelabbench.dashboard.api import app

    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_DB", str(tmp_path / "dashboard.db"))
    DashboardStore(tmp_path / "dashboard.db").create_run(
        SanitizedRunPayload(
            organization_id="org_1",
            run_id="source-run-1",
            project="kinase-demo",
            workflow="predictions",
            metrics={"rmse": 0.4},
        )
    )
    client = TestClient(app)

    ready = client.get("/ready")
    metrics = client.get("/metrics")

    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["counts"]["runs"] == 1
    assert metrics.status_code == 200
    assert "privatelabbench_dashboard_runs 1" in metrics.text
    assert "privatelabbench_dashboard_audit_events 1" in metrics.text


def test_dashboard_rate_limits_requests(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from privatelabbench.dashboard import api as dashboard_api

    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_DB", str(tmp_path / "dashboard.db"))
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_RATE_LIMIT_PER_MINUTE", "2")
    dashboard_api._RATE_LIMIT_BUCKETS.clear()
    client = TestClient(dashboard_api.app)

    assert client.get("/v1/runs").status_code == 200
    assert client.get("/v1/runs").status_code == 200
    limited = client.get("/v1/runs")

    assert limited.status_code == 429
    assert limited.json()["detail"] == "Dashboard API rate limit exceeded."
    assert client.get("/health").status_code == 200


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


def test_dashboard_accepts_trusted_identity_header(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from privatelabbench.dashboard.api import app

    monkeypatch.delenv("PRIVATELABBENCH_DASHBOARD_API_KEY", raising=False)
    monkeypatch.delenv("PRIVATELABBENCH_DASHBOARD_API_KEYS", raising=False)
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_TRUSTED_IDENTITY_HEADER", "x-auth-request-email")
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_ALLOWED_IDENTITY_DOMAINS", "example.com")
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_DB", str(tmp_path / "dashboard.db"))
    client = TestClient(app)

    assert client.get("/").status_code == 401
    assert client.get("/", headers={"x-auth-request-email": "scientist@example.com"}).status_code == 200
    assert client.get("/", headers={"x-auth-request-email": "scientist@other.test"}).status_code == 401


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


def test_dashboard_store_audit_retention_prunes_old_events(tmp_path):
    store = DashboardStore(tmp_path / "dashboard.db")
    old_event = store.add_audit_event("org_1", "old_event", {"ok": True})
    fresh_event = store.add_audit_event("org_1", "fresh_event", {"ok": True})
    old_created_at = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    with store._connect() as conn:
        conn.execute("UPDATE audit_events SET created_at = ? WHERE id = ?", (old_created_at, old_event.id))
        conn.commit()

    deleted = store.prune_audit_events(retention_days=30)
    events = store.list_audit_events(organization_id="org_1")

    assert deleted == 1
    assert [event.id for event in events] == [fresh_event.id]


def test_dashboard_store_backup_restore_roundtrip(tmp_path):
    store = DashboardStore(tmp_path / "dashboard.db")
    store.create_run(
        SanitizedRunPayload(
            organization_id="org_1",
            run_id="source-run-1",
            project="kinase-demo",
            workflow="predictions",
            metrics={"rmse": 0.4},
        )
    )

    backup = store.backup_to(tmp_path / "backups" / "dashboard.backup.db")
    restored = DashboardStore.restore_database(backup, tmp_path / "restored" / "dashboard.db")

    assert backup.is_file()
    assert restored.counts() == {"runs": 1, "evidence": 0, "audit_events": 1}
    assert restored.list_runs()[0].source_run_id == "source-run-1"


def test_dashboard_store_run_sync_is_idempotent_by_org_and_source_run(tmp_path):
    store = DashboardStore(tmp_path / "dashboard.db")
    payload = SanitizedRunPayload(
        organization_id="org_1",
        run_id="source-run-1",
        project="kinase-demo",
        workflow="predictions",
        metrics={"rmse": 0.4},
    )

    first = store.create_run(payload)
    second = store.create_run(payload)

    assert second.id == first.id
    assert len(store.list_runs(project="kinase-demo")) == 1


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


def test_dashboard_evidence_store_and_pages(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from privatelabbench.dashboard.api import app

    monkeypatch.delenv("PRIVATELABBENCH_DASHBOARD_API_KEY", raising=False)
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_DB", str(tmp_path / "dashboard.db"))
    created = DashboardStore(tmp_path / "dashboard.db").create_evidence(
        SanitizedEvidencePayload(
            organization_id="org_1",
            source_run_id="source-run-1",
            source_evidence_id="evidence-sha",
            benchmark_id="kinase-private-v1",
            project="kinase-demo",
            claim="Vendor model improves RMSE",
            recommendation="go",
            decision_status="pass",
            decision_metric="rmse",
            direction="lower_is_better",
            minimum_lift=0.1,
            candidate_value=0.2,
            baseline_value=0.4,
            absolute_delta=0.2,
            relative_lift=0.5,
            privacy={"gate_status": "pass"},
            verification={"manifest_valid": True},
            artifacts=[ArtifactMetadata(name="evidence.json", kind="evidence_json", sha256="abc123")],
            metadata={"dataset_path": "/secret/lab.csv", "task_type": "regression"},
        )
    )
    client = TestClient(app)

    api_response = client.get("/v1/evidence")
    html_response = client.get("/evidence")
    detail_response = client.get(f"/evidence/{created.id}")

    assert api_response.status_code == 200
    assert api_response.json()[0]["recommendation"] == "go"
    assert html_response.status_code == 200
    assert "Vendor model improves RMSE" in html_response.text
    assert f"/evidence/{created.id}" in html_response.text
    assert detail_response.status_code == 200
    assert "evidence_synced" in detail_response.text
    assert "abc123" in detail_response.text
    assert "/secret/lab.csv" not in html_response.text
    assert "/secret/lab.csv" not in detail_response.text


def test_dashboard_evidence_sync_is_idempotent_by_org_and_source_evidence(tmp_path):
    store = DashboardStore(tmp_path / "dashboard.db")
    payload = SanitizedEvidencePayload(
        organization_id="org_1",
        source_evidence_id="evidence-sha",
        project="kinase-demo",
        claim="Vendor model improves RMSE",
        recommendation="go",
        decision_status="pass",
        decision_metric="rmse",
        direction="lower_is_better",
        minimum_lift=0.1,
    )

    first = store.create_evidence(payload)
    second = store.create_evidence(payload)

    assert second.id == first.id
    assert len(store.list_evidence(project="kinase-demo")) == 1


def test_dashboard_enforces_org_scoped_api_key_on_evidence_sync(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from privatelabbench.dashboard.api import app

    monkeypatch.delenv("PRIVATELABBENCH_DASHBOARD_API_KEY", raising=False)
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_API_KEYS", '{"org_1":"org-secret"}')
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_DB", str(tmp_path / "dashboard.db"))
    payload = SanitizedEvidencePayload(
        organization_id="org_1",
        project="kinase-demo",
        claim="Vendor model improves RMSE",
        recommendation="go",
        decision_status="pass",
        decision_metric="rmse",
        direction="lower_is_better",
        minimum_lift=0.1,
    )
    client = TestClient(app)

    assert client.post("/v1/evidence", content=payload.model_dump_json(), headers={"x-api-key": "wrong"}).status_code == 401
    assert client.post("/v1/evidence", content=payload.model_dump_json(), headers={"x-api-key": "org-secret"}).status_code == 200
