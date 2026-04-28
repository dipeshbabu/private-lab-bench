from __future__ import annotations

import os
from pathlib import Path

try:
    from fastapi import Depends, FastAPI, HTTPException, status
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Dashboard API dependencies are missing. Install with: pip install -e '.[api]'") from exc

from privatelabbench.dashboard.auth import require_dashboard_api_key
from privatelabbench.dashboard.schemas import AuditEvent, BenchmarkRun, SanitizedRunPayload
from privatelabbench.dashboard.store import DashboardStore


DASHBOARD_DB_ENV = "PRIVATELABBENCH_DASHBOARD_DB"


def get_store() -> DashboardStore:
    return DashboardStore(Path(os.getenv(DASHBOARD_DB_ENV, ".privatelabbench_dashboard/dashboard.db")))


app = FastAPI(
    title="PrivateLabBench Dashboard API",
    version="0.1.0",
    description="Hosted-dashboard API for sanitized scientific-model benchmark results.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "privatelabbench-dashboard"}


@app.post("/v1/runs", response_model=BenchmarkRun, dependencies=[Depends(require_dashboard_api_key)])
def sync_run(payload: SanitizedRunPayload) -> BenchmarkRun:
    return get_store().create_run(payload)


@app.get("/v1/runs", response_model=list[BenchmarkRun], dependencies=[Depends(require_dashboard_api_key)])
def list_runs(project: str | None = None, limit: int = 50) -> list[BenchmarkRun]:
    return get_store().list_runs(project=project, limit=limit)


@app.get("/v1/runs/{run_id}", response_model=BenchmarkRun, dependencies=[Depends(require_dashboard_api_key)])
def get_run(run_id: str) -> BenchmarkRun:
    run = get_store().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown run_id: {run_id}")
    return run


@app.get("/v1/audit-events", response_model=list[AuditEvent], dependencies=[Depends(require_dashboard_api_key)])
def list_audit_events(organization_id: str | None = None, limit: int = 100) -> list[AuditEvent]:
    return get_store().list_audit_events(organization_id=organization_id, limit=limit)
