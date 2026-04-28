from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

try:
    from fastapi import Depends, FastAPI, Header, HTTPException, status
    from fastapi.responses import FileResponse
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - exercised only when api extra is missing
    raise RuntimeError(
        "PrivateLabBench API dependencies are not installed. "
        "Install them with: pip install -e '.[api]'"
    ) from exc

from privatelabbench.runner import run_config


API_VERSION = "v1"
DEFAULT_RUN_ROOT = Path(os.getenv("PRIVATELABBENCH_RUN_ROOT", ".privatelabbench_api/runs"))
API_KEY_ENV = "PRIVATELABBENCH_API_KEY"


class RunRequest(BaseModel):
    """Request body for launching a benchmark run.

    Use either `config_path` for an existing YAML config on disk, or `config` for an
    inline YAML-equivalent mapping. Inline configs are written into the run folder
    before execution so audit/debug artifacts remain reproducible.
    """

    config_path: str | None = Field(default=None, description="Path to an existing PrivateLabBench YAML config.")
    config: dict[str, Any] | None = Field(default=None, description="Inline PrivateLabBench config mapping.")
    run_id: str | None = Field(default=None, description="Optional caller-provided run id.")


class RunRecord(BaseModel):
    run_id: str
    status: str
    created_at: str
    completed_at: str | None = None
    config_path: str
    summary: dict[str, Any] | None = None
    error: str | None = None


app = FastAPI(
    title="PrivateLabBench API",
    version="0.8.0",
    description="Local-first API for running private scientific model evaluations without uploading raw lab data.",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_root() -> Path:
    root = DEFAULT_RUN_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root


def _record_path(run_id: str) -> Path:
    return _run_root() / f"{run_id}.json"


def _write_record(record: RunRecord) -> None:
    import json

    _record_path(record.run_id).write_text(record.model_dump_json(indent=2), encoding="utf-8")


def _read_record(run_id: str) -> RunRecord:
    import json

    path = _record_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown run_id: {run_id}")
    return RunRecord(**json.loads(path.read_text(encoding="utf-8")))


def _safe_run_id(candidate: str | None) -> str:
    value = candidate or uuid.uuid4().hex[:12]
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    if not value or any(ch not in allowed for ch in value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="run_id may only contain letters, numbers, dashes, and underscores.",
        )
    return value


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.getenv(API_KEY_ENV)
    if expected and x_api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key.")


def _materialize_config(request: RunRequest, run_id: str) -> str:
    if bool(request.config_path) == bool(request.config):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide exactly one of config_path or config.",
        )
    if request.config_path:
        return request.config_path

    run_dir = _run_root() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    config_path = run_dir / "config.yaml"
    config_path.write_text(yaml.safe_dump(request.config, sort_keys=False), encoding="utf-8")
    return str(config_path)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "privatelabbench", "version": "0.8.0"}


@app.post(f"/{API_VERSION}/runs", response_model=RunRecord, dependencies=[Depends(require_api_key)])
def create_run(request: RunRequest) -> RunRecord:
    run_id = _safe_run_id(request.run_id)
    config_path = _materialize_config(request, run_id)
    record = RunRecord(run_id=run_id, status="running", created_at=_utc_now(), config_path=config_path)
    _write_record(record)

    try:
        summary = run_config(config_path)
        record = record.model_copy(update={"status": "completed", "completed_at": _utc_now(), "summary": summary})
    except Exception as exc:  # noqa: BLE001 - API should persist user-visible failure details
        record = record.model_copy(update={"status": "failed", "completed_at": _utc_now(), "error": str(exc)})
    _write_record(record)
    return record


@app.get(f"/{API_VERSION}/runs/{{run_id}}", response_model=RunRecord, dependencies=[Depends(require_api_key)])
def get_run(run_id: str) -> RunRecord:
    return _read_record(run_id)


@app.get(f"/{API_VERSION}/runs/{{run_id}}/report/{{kind}}", dependencies=[Depends(require_api_key)])
def get_report(run_id: str, kind: str) -> FileResponse:
    record = _read_record(run_id)
    if record.status != "completed" or not record.summary:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Run has not completed successfully.")
    key = {"markdown": "markdown_report", "json": "json_report"}.get(kind)
    if key is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="kind must be 'markdown' or 'json'.")
    path = Path(str(record.summary.get(key, "")))
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Report not found: {path}")
    return FileResponse(path)
