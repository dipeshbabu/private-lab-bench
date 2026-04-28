from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib import error, request

from privatelabbench.dashboard.schemas import ArtifactMetadata, SanitizedRunPayload


PRIVATE_KEYS = {
    "dataset_path",
    "directory",
    "target",
    "target_column",
    "prediction_column",
    "prediction_summary",
    "clients",
    "shift",
    "error_slices",
}


def sha256_file(path: str | Path) -> str | None:
    candidate = Path(path)
    if not candidate.exists() or not candidate.is_file():
        return None
    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_summary(summary: dict[str, Any], organization_id: str = "local-org") -> SanitizedRunPayload:
    metrics = summary.get("reported_metrics") or summary.get("aggregate_reported_metrics") or {}
    artifacts: list[ArtifactMetadata] = []
    for key, kind in (("markdown_report", "markdown"), ("json_report", "json"), ("audit_log", "audit")):
        path = summary.get(key)
        if path:
            artifacts.append(
                ArtifactMetadata(
                    name=Path(str(path)).name,
                    kind=kind,
                    sha256=sha256_file(str(path)),
                )
            )

    safe_metadata = {
        key: value
        for key, value in summary.items()
        if key not in PRIVATE_KEYS
        and key not in {"clean_metrics", "reported_metrics", "aggregate_clean_metrics", "aggregate_reported_metrics"}
        and key not in {"markdown_report", "json_report", "audit_log", "privacy"}
        and isinstance(value, (str, int, float, bool, type(None)))
    }

    return SanitizedRunPayload(
        organization_id=organization_id,
        project=str(summary.get("project", "unknown-project")),
        workflow=str(summary.get("workflow", "unknown-workflow")),
        task_type=summary.get("task_type"),
        n_samples=summary.get("n_samples"),
        n_clients=summary.get("n_clients"),
        total_samples=summary.get("total_samples"),
        metrics=metrics,
        privacy=summary.get("privacy", {}),
        artifacts=artifacts,
        metadata=safe_metadata,
    )


def write_sanitized_payload(summary: dict[str, Any], path: str | Path, organization_id: str = "local-org") -> Path:
    payload = sanitize_summary(summary, organization_id=organization_id)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
    return output


def sync_payload(payload: SanitizedRunPayload, endpoint: str, api_key: str | None = None, timeout: float = 20.0) -> dict[str, Any]:
    url = endpoint.rstrip("/") + "/v1/runs"
    data = payload.model_dump_json().encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    req = request.Request(url, data=data, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - user-supplied endpoint is expected for sync command
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Dashboard sync failed with HTTP {exc.code}: {body}") from exc
