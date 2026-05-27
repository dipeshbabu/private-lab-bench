from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:
    from pydantic import BaseModel, Field, field_validator
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Dashboard schemas require pydantic. Install with: pip install -e '.[api]'") from exc


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Organization(BaseModel):
    id: str
    name: str
    created_at: str = Field(default_factory=utc_now)


class Project(BaseModel):
    id: str
    organization_id: str
    name: str
    domain: str = "biotech"
    created_at: str = Field(default_factory=utc_now)


class ArtifactMetadata(BaseModel):
    name: str
    kind: str
    sha256: str | None = None
    uri: str | None = None


class SanitizedRunPayload(BaseModel):
    """Sanitized payload that may be synced to a hosted dashboard.

    This object intentionally excludes raw rows, SMILES strings, model predictions,
    molecule identifiers, free-text lab notes, and local filesystem contents.
    """

    organization_id: str = "local-org"
    run_id: str | None = None
    benchmark_id: str | None = None
    benchmark_version: str | None = None
    benchmark_suite: str | None = None
    domain: str | None = None
    project: str
    workflow: str
    task_type: str | None = None
    n_samples: int | None = None
    n_clients: int | None = None
    total_samples: int | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    privacy: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactMetadata] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)

    @field_validator("metrics")
    @classmethod
    def numeric_metrics_only(cls, value: dict[str, Any]) -> dict[str, float]:
        clean: dict[str, float] = {}
        for key, metric_value in value.items():
            if isinstance(metric_value, bool):
                continue
            if isinstance(metric_value, (int, float)):
                clean[str(key)] = float(metric_value)
        return clean


class BenchmarkRun(BaseModel):
    id: str
    organization_id: str
    source_run_id: str | None = None
    benchmark_id: str | None = None
    benchmark_version: str | None = None
    benchmark_suite: str | None = None
    domain: str | None = None
    project: str
    workflow: str
    status: str = "synced"
    task_type: str | None = None
    n_samples: int | None = None
    n_clients: int | None = None
    total_samples: int | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    privacy: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactMetadata] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    sync_runner_id: str | None = None
    signature_verified: bool | None = None
    signature_algorithm: str | None = None
    signed_payload_sha256: str | None = None
    created_at: str = Field(default_factory=utc_now)


class LeaderboardEntry(BaseModel):
    rank: int
    run_id: str
    source_run_id: str | None = None
    organization_id: str
    project: str
    benchmark_id: str
    benchmark_version: str | None = None
    metric: str
    value: float
    samples: int | None = None
    privacy: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class AuditEvent(BaseModel):
    id: str
    organization_id: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)
