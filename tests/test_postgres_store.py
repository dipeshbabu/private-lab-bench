from __future__ import annotations

import sys
import types

import pytest

from privatelabbench.dashboard.postgres_store import PostgresDashboardStore


class FakeCursor:
    rowcount = 0

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class FakePostgresConnection:
    def __init__(self, queries: list[str]) -> None:
        self.queries = queries

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query: str, params=None):
        self.queries.append(query)
        return FakeCursor()

    def commit(self) -> None:
        return None


def install_fake_psycopg(monkeypatch) -> list[str]:
    queries: list[str] = []
    psycopg_module = types.ModuleType("psycopg")
    rows_module = types.ModuleType("psycopg.rows")
    rows_module.dict_row = object()

    def connect(database_url: str, row_factory=None):
        assert database_url == "postgresql://user:pass@localhost:5432/plb"
        assert row_factory is rows_module.dict_row
        return FakePostgresConnection(queries)

    psycopg_module.connect = connect
    monkeypatch.setitem(sys.modules, "psycopg", psycopg_module)
    monkeypatch.setitem(sys.modules, "psycopg.rows", rows_module)
    return queries


def test_postgres_store_initializes_schema_and_indexes(monkeypatch):
    queries = install_fake_psycopg(monkeypatch)

    PostgresDashboardStore("postgresql://user:pass@localhost:5432/plb")

    joined = "\n".join(queries)
    assert "CREATE TABLE IF NOT EXISTS runs" in joined
    assert "metrics_json JSONB NOT NULL" in joined
    assert "CREATE TABLE IF NOT EXISTS evidence" in joined
    assert "CREATE TABLE IF NOT EXISTS audit_events" in joined
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_source_unique" in joined
    assert "WHERE source_run_id IS NOT NULL" in joined
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_source_unique" in joined
    assert "WHERE source_evidence_id IS NOT NULL" in joined


def test_postgres_store_row_converters_accept_jsonb_values():
    run = PostgresDashboardStore._row_to_run(
        {
            "id": "run_1",
            "organization_id": "org_1",
            "source_run_id": "source-run-1",
            "benchmark_id": "bench",
            "benchmark_version": "2026.06",
            "benchmark_suite": "suite",
            "domain": "molecules",
            "project": "demo",
            "workflow": "predictions",
            "status": "synced",
            "task_type": "regression",
            "n_samples": 10,
            "n_clients": None,
            "total_samples": None,
            "metrics_json": {"rmse": 0.2},
            "privacy_json": {"mode": "dp"},
            "artifacts_json": [{"name": "report.json", "kind": "json"}],
            "metadata_json": {"release": "pilot"},
            "sync_runner_id": "runner",
            "signature_verified": True,
            "signature_algorithm": "ed25519",
            "signed_payload_sha256": "abc123",
            "created_at": "2026-06-16T00:00:00+00:00",
        }
    )

    assert run.metrics == {"rmse": 0.2}
    assert run.artifacts[0].name == "report.json"
    assert run.signature_verified is True


def test_dashboard_store_factory_uses_postgres_url(monkeypatch):
    queries = install_fake_psycopg(monkeypatch)
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_DATABASE_URL", "postgresql://user:pass@localhost:5432/plb")

    from privatelabbench.dashboard.store import create_dashboard_store

    store = create_dashboard_store()

    assert isinstance(store, PostgresDashboardStore)
    assert store.database_url == "postgresql://user:pass@localhost:5432/plb"
    assert queries


def test_dashboard_store_factory_rejects_unsupported_database_url(monkeypatch):
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_DATABASE_URL", "mysql://localhost/db")

    from privatelabbench.dashboard.store import create_dashboard_store

    with pytest.raises(ValueError, match="must start with postgresql:// or postgres://"):
        create_dashboard_store()
