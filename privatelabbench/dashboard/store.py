from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from privatelabbench.dashboard.schemas import (
    AuditEvent,
    BenchmarkRun,
    EvidenceRecord,
    LeaderboardEntry,
    SanitizedEvidencePayload,
    SanitizedRunPayload,
    utc_now,
)


DASHBOARD_DB_ENV = "PRIVATELABBENCH_DASHBOARD_DB"
DASHBOARD_DATABASE_URL_ENV = "PRIVATELABBENCH_DASHBOARD_DATABASE_URL"


def create_dashboard_store() -> Any:
    database_url = os.getenv(DASHBOARD_DATABASE_URL_ENV, "").strip()
    if database_url:
        if database_url.startswith(("postgres://", "postgresql://")):
            from privatelabbench.dashboard.postgres_store import PostgresDashboardStore

            return PostgresDashboardStore(database_url)
        raise ValueError(f"{DASHBOARD_DATABASE_URL_ENV} must start with postgresql:// or postgres://")
    return DashboardStore(Path(os.getenv(DASHBOARD_DB_ENV, ".privatelabbench_dashboard/dashboard.db")))


class DashboardStore:
    """Small SQLite store for evidence-dashboard pilots.

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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    source_run_id TEXT,
                    source_evidence_id TEXT,
                    benchmark_id TEXT,
                    benchmark_version TEXT,
                    benchmark_suite TEXT,
                    domain TEXT,
                    project TEXT NOT NULL,
                    claim TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    decision_status TEXT NOT NULL,
                    decision_metric TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    minimum_lift REAL NOT NULL,
                    candidate_value REAL,
                    baseline_value REAL,
                    absolute_delta REAL,
                    relative_lift REAL,
                    privacy_json TEXT NOT NULL,
                    verification_json TEXT NOT NULL,
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_runs_source ON runs(organization_id, source_run_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_project ON evidence(project)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_org ON evidence(organization_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_recommendation ON evidence(recommendation)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(organization_id, source_evidence_id)")
            conn.commit()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create_run(self, payload: SanitizedRunPayload, signature: dict[str, object] | None = None) -> BenchmarkRun:
        signature = signature or {}
        if payload.run_id:
            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT * FROM runs WHERE organization_id = ? AND source_run_id = ? ORDER BY created_at DESC LIMIT 1",
                    (payload.organization_id, payload.run_id),
                ).fetchone()
            if existing:
                return self._row_to_run(existing)
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

    def create_evidence(
        self,
        payload: SanitizedEvidencePayload,
        signature: dict[str, object] | None = None,
    ) -> EvidenceRecord:
        signature = signature or {}
        if payload.source_evidence_id:
            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT * FROM evidence WHERE organization_id = ? AND source_evidence_id = ? ORDER BY created_at DESC LIMIT 1",
                    (payload.organization_id, payload.source_evidence_id),
                ).fetchone()
            if existing:
                return self._row_to_evidence(existing)
        evidence = EvidenceRecord(
            id=uuid.uuid4().hex[:12],
            organization_id=payload.organization_id,
            source_run_id=payload.source_run_id,
            source_evidence_id=payload.source_evidence_id,
            benchmark_id=payload.benchmark_id,
            benchmark_version=payload.benchmark_version,
            benchmark_suite=payload.benchmark_suite,
            domain=payload.domain,
            project=payload.project,
            claim=payload.claim,
            recommendation=payload.recommendation,
            decision_status=payload.decision_status,
            decision_metric=payload.decision_metric,
            direction=payload.direction,
            minimum_lift=payload.minimum_lift,
            candidate_value=payload.candidate_value,
            baseline_value=payload.baseline_value,
            absolute_delta=payload.absolute_delta,
            relative_lift=payload.relative_lift,
            privacy=payload.privacy,
            verification=payload.verification,
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
                INSERT INTO evidence (
                    id, organization_id, source_run_id, source_evidence_id,
                    benchmark_id, benchmark_version, benchmark_suite, domain,
                    project, claim, recommendation, decision_status,
                    decision_metric, direction, minimum_lift,
                    candidate_value, baseline_value, absolute_delta, relative_lift,
                    privacy_json, verification_json, artifacts_json, metadata_json,
                    sync_runner_id, signature_verified, signature_algorithm,
                    signed_payload_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.id,
                    evidence.organization_id,
                    evidence.source_run_id,
                    evidence.source_evidence_id,
                    evidence.benchmark_id,
                    evidence.benchmark_version,
                    evidence.benchmark_suite,
                    evidence.domain,
                    evidence.project,
                    evidence.claim,
                    evidence.recommendation,
                    evidence.decision_status,
                    evidence.decision_metric,
                    evidence.direction,
                    evidence.minimum_lift,
                    evidence.candidate_value,
                    evidence.baseline_value,
                    evidence.absolute_delta,
                    evidence.relative_lift,
                    json.dumps(evidence.privacy, sort_keys=True),
                    json.dumps(evidence.verification, sort_keys=True),
                    json.dumps([artifact.model_dump() for artifact in evidence.artifacts], sort_keys=True),
                    json.dumps(evidence.metadata, sort_keys=True),
                    evidence.sync_runner_id,
                    None if evidence.signature_verified is None else int(evidence.signature_verified),
                    evidence.signature_algorithm,
                    evidence.signed_payload_sha256,
                    evidence.created_at,
                ),
            )
            conn.commit()
        self.add_audit_event(
            evidence.organization_id,
            "evidence_synced",
            {
                "evidence_id": evidence.id,
                "source_run_id": evidence.source_run_id,
                "source_evidence_id": evidence.source_evidence_id,
                "recommendation": evidence.recommendation,
                "project": evidence.project,
                "sync_runner_id": evidence.sync_runner_id,
                "signature_verified": evidence.signature_verified,
            },
        )
        return evidence

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

    def list_evidence(
        self,
        project: str | None = None,
        recommendation: str | None = None,
        limit: int = 50,
    ) -> list[EvidenceRecord]:
        limit = max(1, min(limit, 200))
        query = "SELECT * FROM evidence"
        params: list[Any] = []
        where: list[str] = []
        if project:
            where.append("project = ?")
            params.append(project)
        if recommendation:
            where.append("recommendation = ?")
            params.append(recommendation)
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_evidence(row) for row in rows]

    def get_evidence(self, evidence_id: str) -> EvidenceRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
        return self._row_to_evidence(row) if row else None

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

    def prune_audit_events(self, retention_days: int) -> int:
        if retention_days < 1:
            raise ValueError("retention_days must be at least 1")
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        cutoff_value = cutoff.isoformat()
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM audit_events WHERE created_at < ?", (cutoff_value,))
            conn.commit()
            return int(cursor.rowcount or 0)

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            return {
                "runs": int(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]),
                "evidence": int(conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]),
                "audit_events": int(conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]),
            }

    def backup_to(self, destination: str | Path) -> Path:
        backup_path = Path(destination)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as source, sqlite3.connect(backup_path) as target:
            source.backup(target)
        return backup_path

    @classmethod
    def restore_database(cls, source: str | Path, destination: str | Path) -> "DashboardStore":
        source_path = Path(source)
        if not source_path.is_file():
            raise FileNotFoundError(f"Dashboard backup not found: {source_path}")
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(source_path) as source_conn, sqlite3.connect(destination_path) as target_conn:
            source_conn.backup(target_conn)
        return cls(destination_path)

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

    @staticmethod
    def _row_to_evidence(row: sqlite3.Row) -> EvidenceRecord:
        return EvidenceRecord(
            id=row["id"],
            organization_id=row["organization_id"],
            source_run_id=row["source_run_id"],
            source_evidence_id=row["source_evidence_id"],
            benchmark_id=row["benchmark_id"],
            benchmark_version=row["benchmark_version"],
            benchmark_suite=row["benchmark_suite"],
            domain=row["domain"],
            project=row["project"],
            claim=row["claim"],
            recommendation=row["recommendation"],
            decision_status=row["decision_status"],
            decision_metric=row["decision_metric"],
            direction=row["direction"],
            minimum_lift=row["minimum_lift"],
            candidate_value=row["candidate_value"],
            baseline_value=row["baseline_value"],
            absolute_delta=row["absolute_delta"],
            relative_lift=row["relative_lift"],
            privacy=json.loads(row["privacy_json"]),
            verification=json.loads(row["verification_json"]),
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
