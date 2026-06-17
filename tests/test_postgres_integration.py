from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os

import pytest

from privatelabbench.dashboard.schemas import SanitizedEvidencePayload, SanitizedRunPayload
from privatelabbench.dashboard.store import create_dashboard_store


pytestmark = pytest.mark.postgres


def postgres_test_url() -> str:
    database_url = os.getenv("PRIVATELABBENCH_TEST_POSTGRES_URL", "").strip()
    if not database_url:
        pytest.skip("Set PRIVATELABBENCH_TEST_POSTGRES_URL to run live PostgreSQL integration tests.")
    try:
        import psycopg  # noqa: F401
    except ImportError:
        pytest.skip("psycopg is not installed. Install with: pip install -e '.[postgres]'.")
    return database_url


@pytest.fixture()
def postgres_store(monkeypatch):
    database_url = postgres_test_url()
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_DATABASE_URL", database_url)
    store = create_dashboard_store()
    _truncate_dashboard_tables(store)
    yield store
    _truncate_dashboard_tables(store)


def _truncate_dashboard_tables(store) -> None:
    with store._connect() as conn:
        conn.execute("TRUNCATE TABLE audit_events, evidence, runs")
        conn.commit()


def test_postgres_dashboard_store_run_roundtrip_idempotency_and_leaderboard(postgres_store):
    payload = SanitizedRunPayload(
        organization_id="org_1",
        run_id="source-run-1",
        benchmark_id="kinase-private-v1",
        benchmark_version="2026.06",
        benchmark_suite="molecular-property",
        domain="molecules",
        project="candidate-a",
        workflow="predictions",
        task_type="regression",
        n_samples=20,
        metrics={"rmse": 0.2},
        privacy={"mode": "dp"},
        metadata={"privacy_gate_publishable": True},
    )

    first = postgres_store.create_run(payload, signature={"verified": True, "algorithm": "ed25519"})
    second = postgres_store.create_run(payload, signature={"verified": True, "algorithm": "ed25519"})
    fetched = postgres_store.get_run(first.id)
    runs = postgres_store.list_runs(project="candidate-a")
    leaderboard = postgres_store.leaderboard(benchmark_id="kinase-private-v1", metric="rmse")
    events = postgres_store.list_audit_events(organization_id="org_1")

    assert second.id == first.id
    assert fetched is not None
    assert fetched.metrics == {"rmse": 0.2}
    assert fetched.signature_verified is True
    assert [run.id for run in runs] == [first.id]
    assert leaderboard[0].run_id == first.id
    assert leaderboard[0].value == 0.2
    assert len(events) == 1
    assert events[0].event_type == "run_synced"
    assert postgres_store.counts() == {"runs": 1, "evidence": 0, "audit_events": 1}


def test_postgres_dashboard_store_evidence_roundtrip_idempotency_and_retention(postgres_store):
    payload = SanitizedEvidencePayload(
        organization_id="org_1",
        source_run_id="source-run-1",
        source_evidence_id="evidence-sha",
        benchmark_id="kinase-private-v1",
        project="candidate-a",
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
        metadata={"release": "pilot"},
    )

    first = postgres_store.create_evidence(payload, signature={"verified": True, "algorithm": "ed25519"})
    second = postgres_store.create_evidence(payload, signature={"verified": True, "algorithm": "ed25519"})
    fetched = postgres_store.get_evidence(first.id)
    old_event = postgres_store.add_audit_event("org_1", "old_event", {"ok": True})
    old_created_at = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    with postgres_store._connect() as conn:
        conn.execute("UPDATE audit_events SET created_at = %s WHERE id = %s", (old_created_at, old_event.id))
        conn.commit()

    deleted = postgres_store.prune_audit_events(retention_days=30)
    evidence = postgres_store.list_evidence(project="candidate-a")
    events = postgres_store.list_audit_events(organization_id="org_1")

    assert second.id == first.id
    assert fetched is not None
    assert fetched.recommendation == "go"
    assert fetched.verification == {"manifest_valid": True}
    assert [record.id for record in evidence] == [first.id]
    assert deleted == 1
    assert [event.event_type for event in events] == ["evidence_synced"]
    assert postgres_store.counts() == {"runs": 0, "evidence": 1, "audit_events": 1}
