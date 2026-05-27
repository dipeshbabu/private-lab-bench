from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from privatelabbench.dashboard.schemas import AuditEvent, BenchmarkRun, LeaderboardEntry, SanitizedRunPayload, utc_now


class DashboardStore:
    """Small SQLite store for hosted-dashboard pilots.

    The store keeps only sanitized run metadata. It is intentionally tiny so the
    same code can run locally, in a demo container, or behind a hosted FastAPI app.
    """

    def __init__(self, path: str | Path = "dashboard.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    source_run_id TEXT,
                    benchmark_id TEXT,
                    benchmark_version TEXT,
                    benchmark_suite TEXT,
                    domain TEXT,
                    project TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    status TEXT NOT NULL,
                    task_type TEXT,
                    n_samples INTEGER,
                    n_clients INTEGER,
                    total_samples INTEGER,
                    metrics_json TEXT NOT NULL,
                    privacy_json TEXT NOT NULL,
                    artifacts_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    sync_runner_id TEXT,
                    signature_verified INTEGER,
                    signature_algorithm TEXT,
                    signed_payload_sha256 TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn, "runs", "source_run_id", "TEXT")
            self._ensure_column(conn, "runs", "benchmark_id", "TEXT")
            self._ensure_column(conn, "runs", "benchmark_version", "TEXT")
            self._ensure_column(conn, "runs", "benchmark_suite", "TEXT")
            self._ensure_column(conn, "runs", "domain", "TEXT")
            self._ensure_column(conn, "runs", "sync_runner_id", "TEXT")
            self._ensure_column(conn, "runs", "signature_verified", "INTEGER")
            self._ensure_column(conn, "runs", "signature_algorithm", "TEXT")
            self._ensure_column(conn, "runs", "signed_payload_sha256", "TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_org ON runs(organization_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_benchmark ON runs(benchmark_id)")
            conn.commit()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create_run(self, payload: SanitizedRunPayload, signature: dict[str, object] | None = None) -> BenchmarkRun:
        signature = signature or {}
        run = BenchmarkRun(
            id=uuid.uuid4().hex[:12],
            organization_id=payload.organization_id,
            source_run_id=payload.run_id,
            benchmark_id=payload.benchmark_id,
            benchmark_version=payload.benchmark_version,
            benchmark_suite=payload.benchmark_suite,
            domain=payload.domain,
            project=payload.project,
            workflow=payload.workflow,
            task_type=payload.task_type,
            n_samples=payload.n_samples,
            n_clients=payload.n_clients,
            total_samples=payload.total_samples,
            metrics=payload.metrics,
            privacy=payload.privacy,
            artifacts=payload.artifacts,
            metadata=payload.metadata,
            sync_runner_id=signature.get("runner_id") if isinstance(signature.get("runner_id"), str) else None,
            signature_verified=(
                bool(signature["verified"]) if isinstance(signature.get("verified"), bool) else None
            ),
            signature_algorithm=signature.get("algorithm") if isinstance(signature.get("algorithm"), str) else None,
            signed_payload_sha256=(
                signature.get("payload_sha256") if isinstance(signature.get("payload_sha256"), str) else None
            ),
            created_at=payload.created_at or utc_now(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    id, organization_id, source_run_id, benchmark_id,
                    benchmark_version, benchmark_suite, domain, project,
                    workflow, status, task_type,
                    n_samples, n_clients, total_samples, metrics_json,
                    privacy_json, artifacts_json, metadata_json,
                    sync_runner_id, signature_verified, signature_algorithm,
                    signed_payload_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.organization_id,
                    run.source_run_id,
                    run.benchmark_id,
                    run.benchmark_version,
                    run.benchmark_suite,
                    run.domain,
                    run.project,
                    run.workflow,
                    run.status,
                    run.task_type,
                    run.n_samples,
                    run.n_clients,
                    run.total_samples,
                    json.dumps(run.metrics, sort_keys=True),
                    json.dumps(run.privacy, sort_keys=True),
                    json.dumps([artifact.model_dump() for artifact in run.artifacts], sort_keys=True),
                    json.dumps(run.metadata, sort_keys=True),
                    run.sync_runner_id,
                    None if run.signature_verified is None else int(run.signature_verified),
                    run.signature_algorithm,
                    run.signed_payload_sha256,
                    run.created_at,
                ),
            )
            conn.commit()
        self.add_audit_event(
            run.organization_id,
            "run_synced",
            {
                "run_id": run.id,
                "source_run_id": run.source_run_id,
                "benchmark_id": run.benchmark_id,
                "sync_runner_id": run.sync_runner_id,
                "signature_verified": run.signature_verified,
                "project": run.project,
            },
        )
        return run

    def list_runs(
        self,
        project: str | None = None,
        benchmark_id: str | None = None,
        limit: int = 50,
    ) -> list[BenchmarkRun]:
        limit = max(1, min(limit, 200))
        query = "SELECT * FROM runs"
        params: list[Any] = []
        where: list[str] = []
        if project:
            where.append("project = ?")
            params.append(project)
        if benchmark_id:
            where.append("benchmark_id = ?")
            params.append(benchmark_id)
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_run(row) for row in rows]

    def get_run(self, run_id: str) -> BenchmarkRun | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._row_to_run(row) if row else None

    def leaderboard(
        self,
        *,
        benchmark_id: str,
        metric: str,
        order: str = "asc",
        require_publishable: bool = True,
        limit: int = 50,
    ) -> list[LeaderboardEntry]:
        if order not in {"asc", "desc"}:
            raise ValueError("order must be 'asc' or 'desc'")
        runs = self.list_runs(benchmark_id=benchmark_id, limit=200)
        eligible: list[BenchmarkRun] = []
        for run in runs:
            if metric not in run.metrics:
                continue
            if require_publishable and run.metadata.get("privacy_gate_publishable") is False:
                continue
            eligible.append(run)

        reverse = order == "desc"
        eligible.sort(key=lambda run: (float(run.metrics[metric]), run.created_at), reverse=reverse)
        entries: list[LeaderboardEntry] = []
        for rank, run in enumerate(eligible[: max(1, min(limit, 200))], start=1):
            entries.append(
                LeaderboardEntry(
                    rank=rank,
                    run_id=run.id,
                    source_run_id=run.source_run_id,
                    organization_id=run.organization_id,
                    project=run.project,
                    benchmark_id=run.benchmark_id or benchmark_id,
                    benchmark_version=run.benchmark_version,
                    metric=metric,
                    value=float(run.metrics[metric]),
                    samples=run.total_samples or run.n_samples,
                    privacy=run.privacy,
                    metadata=run.metadata,
                    created_at=run.created_at,
                )
            )
        return entries

    def add_audit_event(self, organization_id: str, event_type: str, payload: dict[str, Any]) -> AuditEvent:
        event = AuditEvent(
            id=uuid.uuid4().hex[:12],
            organization_id=organization_id,
            event_type=event_type,
            payload=payload,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (id, organization_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (event.id, event.organization_id, event.event_type, json.dumps(event.payload, sort_keys=True), event.created_at),
            )
            conn.commit()
        return event

    def list_audit_events(self, organization_id: str | None = None, limit: int = 100) -> list[AuditEvent]:
        limit = max(1, min(limit, 500))
        query = "SELECT * FROM audit_events"
        params: list[Any] = []
        if organization_id:
            query += " WHERE organization_id = ?"
            params.append(organization_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            AuditEvent(
                id=row["id"],
                organization_id=row["organization_id"],
                event_type=row["event_type"],
                payload=json.loads(row["payload_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> BenchmarkRun:
        return BenchmarkRun(
            id=row["id"],
            organization_id=row["organization_id"],
            source_run_id=row["source_run_id"],
            benchmark_id=row["benchmark_id"],
            benchmark_version=row["benchmark_version"],
            benchmark_suite=row["benchmark_suite"],
            domain=row["domain"],
            project=row["project"],
            workflow=row["workflow"],
            status=row["status"],
            task_type=row["task_type"],
            n_samples=row["n_samples"],
            n_clients=row["n_clients"],
            total_samples=row["total_samples"],
            metrics=json.loads(row["metrics_json"]),
            privacy=json.loads(row["privacy_json"]),
            artifacts=json.loads(row["artifacts_json"]),
            metadata=json.loads(row["metadata_json"]),
            sync_runner_id=row["sync_runner_id"],
            signature_verified=(
                None if row["signature_verified"] is None else bool(row["signature_verified"])
            ),
            signature_algorithm=row["signature_algorithm"],
            signed_payload_sha256=row["signed_payload_sha256"],
            created_at=row["created_at"],
        )
