from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib import error, request

from privatelabbench.dashboard.schemas import ArtifactMetadata, SanitizedRunPayload
from privatelabbench.identity import RUNNER_ID_ENV
from privatelabbench.signing import RUNNER_PRIVATE_KEY_ENV, SIGNATURE_ALGORITHM, payload_sha256, sign_payload


PRIVATE_KEYS = {
    "dataset_path",
    "directory",
    "target",
    "target_column",
    "prediction_column",
    "split_column",
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


def sanitize_privacy(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {"summary": str(value)}


def sanitize_summary(summary: dict[str, Any], organization_id: str = "local-org") -> SanitizedRunPayload:
    metrics = summary.get("reported_metrics") or summary.get("aggregate_reported_metrics") or {}
    artifacts: list[ArtifactMetadata] = []
    for key, kind in (
        ("markdown_report", "markdown"),
        ("json_report", "json"),
        ("audit_log", "audit"),
        ("manifest", "manifest"),
    ):
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
        and key not in {"markdown_report", "json_report", "audit_log", "manifest", "privacy"}
        and isinstance(value, (str, int, float, bool, type(None)))
    }

    return SanitizedRunPayload(
        organization_id=organization_id,
        run_id=summary.get("run_id"),
        benchmark_id=summary.get("benchmark_id"),
        benchmark_version=summary.get("benchmark_version"),
        benchmark_suite=summary.get("benchmark_suite"),
        domain=summary.get("domain"),
        project=str(summary.get("project", "unknown-project")),
        workflow=str(summary.get("workflow", "unknown-workflow")),
        task_type=summary.get("task_type"),
        n_samples=summary.get("n_samples"),
        n_clients=summary.get("n_clients"),
        total_samples=summary.get("total_samples"),
        metrics=metrics,
        privacy=sanitize_privacy(summary.get("privacy")),
        artifacts=artifacts,
        metadata=safe_metadata,
    )


def write_sanitized_payload(summary: dict[str, Any], path: str | Path, organization_id: str = "local-org") -> Path:
    payload = sanitize_summary(summary, organization_id=organization_id)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
    return output


def signed_sync_headers(
    payload_bytes: bytes,
    *,
    runner_id: str | None = None,
    private_key: str | None = None,
) -> dict[str, str]:
    key = private_key or os.getenv(RUNNER_PRIVATE_KEY_ENV)
    resolved_runner_id = runner_id or os.getenv(RUNNER_ID_ENV)
    if not key and not resolved_runner_id:
        return {}
    if not key or not resolved_runner_id:
        raise ValueError("Signed sync requires both runner_id and runner private key.")
    return {
        "X-Runner-ID": resolved_runner_id,
        "X-Runner-Signature-Alg": SIGNATURE_ALGORITHM,
        "X-Runner-Payload-SHA256": payload_sha256(payload_bytes),
        "X-Runner-Signature": sign_payload(payload_bytes, key),
    }


def sync_payload(
    payload: SanitizedRunPayload,
    endpoint: str,
    api_key: str | None = None,
    timeout: float = 20.0,
    *,
    runner_id: str | None = None,
    runner_private_key: str | None = None,
) -> dict[str, Any]:
    url = endpoint.rstrip("/") + "/v1/runs"
    data = payload.model_dump_json().encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    headers.update(signed_sync_headers(data, runner_id=runner_id, private_key=runner_private_key))
    req = request.Request(url, data=data, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - user-supplied endpoint is expected for sync command
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Dashboard sync failed with HTTP {exc.code}: {body}") from exc
