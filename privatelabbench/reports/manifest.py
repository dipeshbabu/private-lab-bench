from __future__ import annotations

import json
import hashlib
import hmac
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from privatelabbench import __version__
from privatelabbench.attestation import collect_runner_attestation
from privatelabbench.reports.integrity import attach_integrity_metadata, verify_report


def sha256_file(path: str | Path) -> str:
    digest_path = Path(path)
    digest = hashlib.sha256()
    with digest_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(kind: str, path: str | Path | None, *, required: bool = True) -> dict[str, Any] | None:
    if not path:
        return None
    artifact_path = Path(path)
    if not artifact_path.exists():
        if required:
            raise FileNotFoundError(f"Manifest artifact does not exist: {artifact_path}")
        return None
    return {
        "kind": kind,
        "path": str(artifact_path),
        "name": artifact_path.name,
        "sha256": sha256_file(artifact_path),
    }


def build_run_manifest(
    *,
    summary: Mapping[str, Any],
    config_path: str | Path,
    json_report_path: str | Path,
    audit_log_path: str | Path,
    markdown_report_path: str | Path | None = None,
    signing_secret: str | None = None,
) -> dict[str, Any]:
    report_path = Path(json_report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report_integrity = report.get("integrity", {}) if isinstance(report, dict) else {}

    artifacts = [
        artifact
        for artifact in (
            _artifact("config", config_path),
            _artifact("json_report", json_report_path),
            _artifact("markdown_report", markdown_report_path, required=False),
            _artifact("audit_log", audit_log_path),
        )
        if artifact is not None
    ]

    payload: dict[str, Any] = {
        "schema_version": "run-manifest/v0.1",
        "manifest_id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "package": {"name": "private-lab-bench", "version": __version__},
        "run": {
            "run_id": summary.get("run_id") or report.get("run_id"),
            "project": summary.get("project"),
            "workflow": summary.get("workflow"),
            "report_type": report.get("report_type"),
            "report_payload_sha256": report_integrity.get("payload_sha256"),
            "report_signed": bool(report_integrity.get("signed", False)),
        },
        "benchmark": {
            "id": summary.get("benchmark_id"),
            "version": summary.get("benchmark_version"),
            "suite": summary.get("benchmark_suite"),
            "domain": summary.get("domain"),
            "protocol": summary.get("benchmark_protocol"),
        },
        "runner": {
            "id": summary.get("runner_id"),
            "label": summary.get("runner_label"),
        },
        "attestation": collect_runner_attestation(),
        "privacy": report.get("privacy", {}),
        "artifacts": artifacts,
    }
    return attach_integrity_metadata(payload, signing_secret=signing_secret)


def write_run_manifest(
    output_path: str | Path,
    *,
    summary: Mapping[str, Any],
    config_path: str | Path,
    json_report_path: str | Path,
    audit_log_path: str | Path,
    markdown_report_path: str | Path | None = None,
    signing_secret: str | None = None,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_run_manifest(
        summary=summary,
        config_path=config_path,
        json_report_path=json_report_path,
        audit_log_path=audit_log_path,
        markdown_report_path=markdown_report_path,
        signing_secret=signing_secret,
    )
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def verify_run_manifest(path: str | Path, *, signing_secret: str | None = None) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    integrity = manifest.get("integrity")
    if not isinstance(integrity, dict):
        return {"valid": False, "reason": "missing_integrity_metadata", "path": str(manifest_path)}

    from privatelabbench.reports.integrity import compute_payload_sha256, sign_payload

    expected_hash = str(integrity.get("payload_sha256", ""))
    actual_hash = compute_payload_sha256(manifest)
    hash_valid = bool(expected_hash) and hmac.compare_digest(expected_hash, actual_hash)

    signature_valid = None
    if signing_secret:
        expected_signature = str(integrity.get("signature", ""))
        actual_signature = sign_payload(manifest, signing_secret)
        signature_valid = bool(expected_signature) and hmac.compare_digest(expected_signature, actual_signature)

    artifact_results: list[dict[str, Any]] = []
    artifacts_valid = True
    report_valid = True
    for artifact in manifest.get("artifacts", []):
        artifact_path = Path(str(artifact.get("path", "")))
        exists = artifact_path.exists()
        actual_artifact_hash = sha256_file(artifact_path) if exists else None
        expected_artifact_hash = artifact.get("sha256")
        valid_hash = exists and actual_artifact_hash == expected_artifact_hash
        artifact_results.append(
            {
                "kind": artifact.get("kind"),
                "path": str(artifact_path),
                "exists": exists,
                "hash_valid": valid_hash,
                "sha256": actual_artifact_hash,
                "expected_sha256": expected_artifact_hash,
            }
        )
        artifacts_valid = artifacts_valid and bool(valid_hash)
        if artifact.get("kind") == "json_report" and exists:
            report_check = verify_report(str(artifact_path), signing_secret=signing_secret)
            report_valid = bool(report_check["valid"])
            artifact_results[-1]["report_integrity_valid"] = report_valid

    valid = hash_valid and artifacts_valid and report_valid and (signature_valid is not False)
    reason = "ok"
    if not hash_valid:
        reason = "manifest_hash_check_failed"
    elif signature_valid is False:
        reason = "manifest_signature_check_failed"
    elif not report_valid:
        reason = "report_integrity_check_failed"
    elif not artifacts_valid:
        reason = "artifact_hash_check_failed"

    return {
        "valid": valid,
        "reason": reason,
        "path": str(manifest_path),
        "manifest_id": manifest.get("manifest_id"),
        "run_id": manifest.get("run", {}).get("run_id"),
        "payload_sha256": actual_hash,
        "expected_payload_sha256": expected_hash,
        "hash_valid": hash_valid,
        "signature_valid": signature_valid,
        "artifacts_valid": artifacts_valid,
        "report_valid": report_valid,
        "artifacts": artifact_results,
    }
