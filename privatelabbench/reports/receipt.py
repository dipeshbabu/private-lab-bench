from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from privatelabbench.reports.integrity import attach_integrity_metadata, verify_report

RECEIPT_SCHEMA_VERSION = "evaluation-receipt/v1"
LEGACY_MANIFEST_SCHEMA = "run-manifest/v0.1"


def _read_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _reported_metrics(result: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    if isinstance(result.get("reported_metrics"), Mapping):
        return "reported_metrics", dict(result["reported_metrics"])
    if isinstance(result.get("aggregate_reported_metrics"), Mapping):
        return "aggregate_reported_metrics", dict(result["aggregate_reported_metrics"])
    if isinstance(result.get("clean_metrics"), Mapping):
        return "clean_metrics", dict(result["clean_metrics"])
    if isinstance(result.get("aggregate_clean_metrics"), Mapping):
        return "aggregate_clean_metrics", dict(result["aggregate_clean_metrics"])
    return "none", {}


def _clean_metrics(result: Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(result.get("clean_metrics"), Mapping):
        return dict(result["clean_metrics"])
    if isinstance(result.get("aggregate_clean_metrics"), Mapping):
        return dict(result["aggregate_clean_metrics"])
    return {}


def _sample_counts(result: Mapping[str, Any]) -> dict[str, int]:
    keys = ("n_samples", "n_train", "n_test", "n_clients", "total_samples")
    out: dict[str, int] = {}
    for key in keys:
        value = result.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[key] = int(value)
    return out


def _input_schema(result: Mapping[str, Any]) -> dict[str, Any]:
    schema = result.get("prediction_table_schema")
    if isinstance(schema, Mapping):
        return dict(schema)
    out: dict[str, Any] = {"schema_version": "legacy-task-input/v1"}
    for key in ("target_column", "prediction_column", "task_type", "adapter", "fingerprint"):
        if result.get(key) is not None:
            out[key] = result.get(key)
    return out


def _privacy_summary(report: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    privacy = dict(report.get("privacy", {})) if isinstance(report.get("privacy"), Mapping) else {}
    audits: dict[str, Any] = {}
    if isinstance(result.get("privacy_risk"), Mapping) and result.get("privacy_risk"):
        audits["membership_inference"] = dict(result["privacy_risk"])
    release: dict[str, Any] = {"status": "not_evaluated"}
    if isinstance(result.get("privacy_gate"), Mapping) and result.get("privacy_gate"):
        release = dict(result["privacy_gate"])
    elif isinstance(result.get("aggregate_release"), Mapping) and result.get("aggregate_release"):
        release = dict(result["aggregate_release"])
    return {"mechanism": privacy, "audits": audits, "release": release}


def _public_artifacts(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    artifacts = []
    for artifact in manifest.get("artifacts", []):
        if not isinstance(artifact, Mapping):
            continue
        artifacts.append({"kind": artifact.get("kind"), "name": artifact.get("name"), "sha256": artifact.get("sha256")})
    return artifacts


def _local_paths(manifest: Mapping[str, Any]) -> dict[str, str]:
    paths: dict[str, str] = {}
    for artifact in manifest.get("artifacts", []):
        if not isinstance(artifact, Mapping):
            continue
        kind = artifact.get("kind")
        path = artifact.get("path")
        if kind and path:
            paths[str(kind)] = str(path)
    return paths


def build_evaluation_receipt(
    *,
    summary: Mapping[str, Any],
    report_path: str | Path,
    manifest_path: str | Path,
    config_path: str | Path,
    signing_secret: str | None = None,
    receipt_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    report = _read_json(report_path)
    manifest = _read_json(manifest_path)
    result = report.get("result", {})
    if not isinstance(result, Mapping):
        result = {}
    metric_source, metrics = _reported_metrics(result)
    clean_metrics = _clean_metrics(result)
    extra = report.get("extra", {}) if isinstance(report.get("extra"), Mapping) else {}
    attestation = manifest.get("attestation", {}) if isinstance(manifest.get("attestation"), Mapping) else {}

    shareable = {
        "run": {
            "run_id": report.get("run_id") or summary.get("run_id"),
            "created_at": report.get("created_at"),
            "project": summary.get("project"),
            "task": summary.get("task") or summary.get("workflow"),
            "report_type": report.get("report_type"),
        },
        "benchmark": {
            "id": summary.get("benchmark_id") or extra.get("benchmark_id"),
            "version": summary.get("benchmark_version") or extra.get("benchmark_version"),
            "suite": summary.get("benchmark_suite") or extra.get("benchmark_suite"),
            "domain": summary.get("domain") or extra.get("domain"),
            "protocol": summary.get("benchmark_protocol") or extra.get("benchmark_protocol"),
        },
        "evaluation": {
            "task_type": result.get("task_type"),
            "sample_counts": _sample_counts(result),
            "input_schema": _input_schema(result),
            "metrics": metrics,
            "metric_source": metric_source,
            "uncertainty": dict(result.get("uncertainty", {})) if isinstance(result.get("uncertainty"), Mapping) else {},
            "slices": dict(result.get("slice_metrics", {})) if isinstance(result.get("slice_metrics"), Mapping) else {},
        },
        "privacy": _privacy_summary(report, result),
        "provenance": {"package": manifest.get("package", {}), "attestation_id": attestation.get("attestation_id")},
        "artifacts": _public_artifacts(manifest),
    }

    local = {
        "sharing": "local_only",
        "paths": {**_local_paths(manifest), "manifest": str(manifest_path), "receipt_source_report": str(report_path), "config": str(config_path)},
        "config_snapshot": report.get("config_snapshot", {}),
        "exact_metrics": clean_metrics,
        "runner": manifest.get("runner", {}),
        "attestation": manifest.get("attestation", {}),
        "manifest_integrity": manifest.get("integrity", {}),
    }

    payload = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "receipt_id": receipt_id or str(uuid4()),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "scope": "local",
        "shareable": shareable,
        "local": local,
    }
    return attach_integrity_metadata(payload, signing_secret=signing_secret)


def make_shareable_receipt(receipt: Mapping[str, Any], *, signing_secret: str | None = None) -> dict[str, Any]:
    normalized = normalize_receipt(receipt)
    payload = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "receipt_id": normalized.get("receipt_id"),
        "created_at": normalized.get("created_at"),
        "scope": "shareable",
        "shareable": normalized.get("shareable", {}),
    }
    return attach_integrity_metadata(payload, signing_secret=signing_secret)


def receipt_from_legacy_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    if manifest.get("schema_version") != LEGACY_MANIFEST_SCHEMA:
        raise ValueError(f"Expected {LEGACY_MANIFEST_SCHEMA}; found {manifest.get('schema_version')!r}")
    run = manifest.get("run", {}) if isinstance(manifest.get("run"), Mapping) else {}
    benchmark = manifest.get("benchmark", {}) if isinstance(manifest.get("benchmark"), Mapping) else {}
    attestation = manifest.get("attestation", {}) if isinstance(manifest.get("attestation"), Mapping) else {}
    payload = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "receipt_id": f"legacy-manifest:{manifest.get('manifest_id', 'unknown')}",
        "created_at": manifest.get("created_at"),
        "scope": "compatibility",
        "shareable": {
            "run": {"run_id": run.get("run_id"), "created_at": manifest.get("created_at"), "project": run.get("project"), "task": run.get("task") or run.get("workflow"), "report_type": run.get("report_type")},
            "benchmark": dict(benchmark),
            "evaluation": {"task_type": None, "sample_counts": {}, "input_schema": {"schema_version": "legacy-manifest/unknown-input"}, "metrics": {}, "metric_source": "not_present_in_legacy_manifest", "uncertainty": {}, "slices": {}},
            "privacy": {"mechanism": manifest.get("privacy", {}), "audits": {}, "release": {"status": "not_present_in_legacy_manifest"}},
            "provenance": {"package": manifest.get("package", {}), "attestation_id": attestation.get("attestation_id")},
            "artifacts": _public_artifacts(manifest),
        },
        "local": {"sharing": "local_only", "legacy_schema": LEGACY_MANIFEST_SCHEMA, "paths": _local_paths(manifest), "runner": manifest.get("runner", {}), "attestation": manifest.get("attestation", {})},
    }
    return attach_integrity_metadata(payload)


def normalize_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    schema = payload.get("schema_version")
    if schema == RECEIPT_SCHEMA_VERSION:
        return dict(payload)
    if schema == LEGACY_MANIFEST_SCHEMA:
        return receipt_from_legacy_manifest(payload)
    raise ValueError(f"Unsupported receipt schema_version: {schema!r}")


def validate_receipt_shape(payload: Mapping[str, Any]) -> None:
    normalized = normalize_receipt(payload)
    if not normalized.get("receipt_id"):
        raise ValueError("Receipt is missing receipt_id")
    if normalized.get("scope") not in {"local", "shareable", "compatibility"}:
        raise ValueError(f"Unsupported receipt scope: {normalized.get('scope')!r}")
    shareable = normalized.get("shareable")
    if not isinstance(shareable, Mapping):
        raise ValueError("Receipt is missing shareable section")
    for section in ("run", "benchmark", "evaluation", "privacy", "provenance", "artifacts"):
        if section not in shareable:
            raise ValueError(f"Receipt shareable section is missing {section!r}")


def verify_receipt(path: str | Path, *, signing_secret: str | None = None) -> dict[str, Any]:
    receipt_path = Path(path)
    payload = _read_json(receipt_path)
    try:
        validate_receipt_shape(payload)
    except ValueError as exc:
        return {"valid": False, "reason": "invalid_receipt_schema", "error": str(exc), "path": str(receipt_path)}
    result = verify_report(str(receipt_path), signing_secret=signing_secret)
    result["schema_version"] = payload.get("schema_version")
    result["scope"] = payload.get("scope")
    result["receipt_id"] = payload.get("receipt_id")
    return result


def _format_metrics(metrics: Mapping[str, Any]) -> list[str]:
    lines = []
    for key, value in metrics.items():
        if isinstance(value, float):
            lines.append(f"- {key}: {value:.6f}")
        else:
            lines.append(f"- {key}: {value}")
    return lines


def render_receipt_markdown(receipt: Mapping[str, Any]) -> str:
    normalized = normalize_receipt(receipt)
    shareable = normalized["shareable"]
    run = shareable["run"]
    benchmark = shareable["benchmark"]
    evaluation = shareable["evaluation"]
    privacy = shareable["privacy"]
    provenance = shareable["provenance"]

    lines = [
        "# PrivateLabBench Evaluation Receipt",
        "",
        f"- Receipt schema: `{RECEIPT_SCHEMA_VERSION}`",
        f"- Receipt ID: `{normalized.get('receipt_id')}`",
        f"- Run ID: `{run.get('run_id')}`",
        f"- Project: {run.get('project')}",
        f"- Task: {run.get('task')}",
        f"- Report type: {run.get('report_type')}",
        "",
        "## Benchmark",
        f"- ID: {benchmark.get('id')}",
        f"- Version: {benchmark.get('version')}",
        f"- Suite: {benchmark.get('suite')}",
        f"- Domain: {benchmark.get('domain')}",
        "",
        "## Evaluation",
        f"- Task type: {evaluation.get('task_type')}",
        f"- Metric source: {evaluation.get('metric_source')}",
    ]
    for key, value in evaluation.get("sample_counts", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "### Metrics"])
    lines.extend(_format_metrics(evaluation.get("metrics", {})) or ["- (none)"])
    slices = evaluation.get("slices", {})
    if slices:
        lines.extend(["", "### Slices"])
        for column, groups in slices.items():
            lines.append(f"- `{column}`: {len(groups)} group(s)")
    lines.extend(["", "## Privacy and release", f"- Mechanism mode: {privacy.get('mechanism', {}).get('mode')}", f"- Release status: {privacy.get('release', {}).get('status', 'not_evaluated')}", f"- Privacy audits: {', '.join(privacy.get('audits', {}).keys()) or '(none)'}", "", "## Provenance", f"- Package: {provenance.get('package', {}).get('name')} {provenance.get('package', {}).get('version')}", f"- Attestation ID: {provenance.get('attestation_id')}", "", "## Artifact hashes"])
    artifacts = shareable.get("artifacts", [])
    if artifacts:
        for artifact in artifacts:
            lines.append(f"- {artifact.get('kind')}: `{artifact.get('name')}` — `{artifact.get('sha256')}`")
    else:
        lines.append("- (none)")
    lines.extend(["", "## Sharing boundary", "This rendering is derived only from the receipt's `shareable` section.", "Local paths, config snapshots, exact local-only metrics, and full runner attestation are excluded."])
    return "\n".join(lines) + "\n"


def write_evaluation_receipts(
    *,
    full_path: str | Path,
    shareable_path: str | Path,
    markdown_path: str | Path,
    summary: Mapping[str, Any],
    report_path: str | Path,
    manifest_path: str | Path,
    config_path: str | Path,
    signing_secret: str | None = None,
) -> dict[str, Path]:
    full = build_evaluation_receipt(summary=summary, report_path=report_path, manifest_path=manifest_path, config_path=config_path, signing_secret=signing_secret)
    shareable = make_shareable_receipt(full, signing_secret=signing_secret)
    full_output = Path(full_path)
    shareable_output = Path(shareable_path)
    markdown_output = Path(markdown_path)
    for output in (full_output, shareable_output, markdown_output):
        output.parent.mkdir(parents=True, exist_ok=True)
    full_output.write_text(json.dumps(full, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    shareable_output.write_text(json.dumps(shareable, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_output.write_text(render_receipt_markdown(shareable), encoding="utf-8")
    return {"receipt": full_output, "receipt_shareable": shareable_output, "receipt_markdown": markdown_output}
