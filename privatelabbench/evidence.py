from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

from privatelabbench.config import load_config, section
from privatelabbench.eval.metrics import summarize_metrics
from privatelabbench.eval.predictions import evaluate_prediction_csv
from privatelabbench.reports.integrity import attach_integrity_metadata, verify_report
from privatelabbench.reports.json import write_json_report
from privatelabbench.reports.manifest import sha256_file, verify_run_manifest
from privatelabbench.runner import _input_path, _privacy_config, _report_path, _signing_secret, run_config


LOWER_IS_BETTER = {"mae", "mse", "rmse", "loss", "error"}
HIGHER_IS_BETTER = {"accuracy", "f1", "auroc", "auc", "r2", "precision", "recall"}
VALID_DIRECTIONS = {"lower_is_better", "higher_is_better"}


def _claim_section(config: Mapping[str, Any], claim_override: str | None) -> dict[str, Any]:
    claim = config.get("claim", {})
    if claim is None:
        claim = {}
    if not isinstance(claim, dict):
        raise ValueError("claim must be a mapping when provided.")
    merged = dict(claim)
    if claim_override:
        merged["text"] = claim_override
    return merged


def infer_metric_direction(metric: str) -> str:
    normalized = metric.strip().lower()
    if normalized in LOWER_IS_BETTER or any(token in normalized for token in LOWER_IS_BETTER):
        return "lower_is_better"
    if normalized in HIGHER_IS_BETTER or any(token in normalized for token in HIGHER_IS_BETTER):
        return "higher_is_better"
    return "higher_is_better"


def default_decision_metric(task_type: str, metrics: Mapping[str, float]) -> str:
    preferred = ["rmse", "mae", "r2"] if task_type == "regression" else ["auroc", "f1", "accuracy"]
    for metric in preferred:
        if metric in metrics:
            return metric
    if not metrics:
        raise ValueError("Cannot choose a decision metric because no metrics were produced.")
    return next(iter(metrics.keys()))


def compare_metric(
    *,
    candidate_metrics: Mapping[str, float],
    baseline_metrics: Mapping[str, float] | None,
    metric: str,
    direction: str,
    minimum_lift: float,
) -> dict[str, Any]:
    if direction not in VALID_DIRECTIONS:
        raise ValueError("claim.direction must be 'lower_is_better' or 'higher_is_better'.")
    if metric not in candidate_metrics:
        return {
            "status": "needs_review",
            "metric": metric,
            "direction": direction,
            "minimum_lift": minimum_lift,
            "reason": "decision_metric_missing_from_candidate",
        }
    if not baseline_metrics:
        return {
            "status": "needs_review",
            "metric": metric,
            "direction": direction,
            "minimum_lift": minimum_lift,
            "candidate_value": candidate_metrics[metric],
            "reason": "baseline_missing",
        }
    if metric not in baseline_metrics:
        return {
            "status": "needs_review",
            "metric": metric,
            "direction": direction,
            "minimum_lift": minimum_lift,
            "candidate_value": candidate_metrics[metric],
            "reason": "decision_metric_missing_from_baseline",
        }

    candidate = float(candidate_metrics[metric])
    baseline = float(baseline_metrics[metric])
    if not math.isfinite(candidate) or not math.isfinite(baseline):
        return {
            "status": "needs_review",
            "metric": metric,
            "direction": direction,
            "minimum_lift": minimum_lift,
            "candidate_value": candidate,
            "baseline_value": baseline,
            "reason": "decision_metric_not_finite",
        }

    if direction == "lower_is_better":
        absolute_delta = baseline - candidate
        relative_lift = absolute_delta / abs(baseline) if baseline else absolute_delta
    else:
        absolute_delta = candidate - baseline
        relative_lift = absolute_delta / abs(baseline) if baseline else absolute_delta
    meets_direction = absolute_delta >= 0
    meets_minimum_lift = relative_lift >= minimum_lift
    return {
        "status": "pass" if meets_direction and meets_minimum_lift else "fail",
        "metric": metric,
        "direction": direction,
        "minimum_lift": minimum_lift,
        "candidate_value": candidate,
        "baseline_value": baseline,
        "absolute_delta": absolute_delta,
        "relative_lift": relative_lift,
        "meets_direction": meets_direction,
        "meets_minimum_lift": meets_minimum_lift,
    }


def recommendation_from_evidence(
    *,
    comparison: Mapping[str, Any],
    privacy_gate_publishable: bool | None,
    manifest_valid: bool,
) -> dict[str, Any]:
    reasons: list[str] = []
    if not manifest_valid:
        reasons.append("evidence_verification_failed")
    if privacy_gate_publishable is False:
        reasons.append("privacy_gate_failed")

    comparison_status = str(comparison.get("status", "needs_review"))
    if comparison_status == "needs_review":
        reasons.append(str(comparison.get("reason", "comparison_needs_review")))
    elif comparison_status == "fail":
        reasons.append("minimum_model_lift_not_met")

    if reasons:
        if "evidence_verification_failed" in reasons or "privacy_gate_failed" in reasons or comparison_status == "fail":
            recommendation = "no-go"
        else:
            recommendation = "needs-review"
    else:
        recommendation = "go"

    return {
        "recommendation": recommendation,
        "status": "pass" if recommendation == "go" else ("fail" if recommendation == "no-go" else "needs_review"),
        "reasons": reasons,
    }


def _baseline_evaluation(config: Any) -> tuple[str | None, dict[str, float] | None]:
    input_cfg = section(config, "input")
    baseline_column = input_cfg.get("baseline_prediction_column")
    if not baseline_column:
        return None, None
    path = _input_path(config, str(input_cfg["path"]))
    baseline = evaluate_prediction_csv(
        path,
        target=str(input_cfg["target_column"]),
        prediction_column=str(baseline_column),
        task_type=input_cfg.get("task_type"),
        split_column=str(input_cfg["split_column"]) if input_cfg.get("split_column") else None,
    )
    return str(baseline_column), baseline.metrics


def _sharing_summary() -> dict[str, list[str]]:
    return {
        "stays_local": [
            "raw CSV rows",
            "target and prediction columns",
            "local dataset paths",
            "full local reports unless the customer chooses to share them",
            "model code and model outputs",
            "audit JSONL files unless the customer chooses to share them",
        ],
        "safe_to_share": [
            "evidence report markdown",
            "evidence report JSON with integrity metadata",
            "sanitized run metadata",
            "reported metrics",
            "privacy gate status",
            "artifact names and SHA256 hashes",
            "manifest verification result",
        ],
    }


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6f}" if math.isfinite(value) else "nan"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _format_lines(values: Mapping[str, Any]) -> list[str]:
    return [f"- {key}: {_format_value(value)}" for key, value in values.items()]


def write_evidence_markdown(output_path: str, evidence: Mapping[str, Any]) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    claim = evidence["claim"]
    model = evidence["model_under_test"]
    baseline = evidence.get("baseline") or {}
    decision = evidence["decision"]
    privacy = evidence["privacy"]
    verification = evidence["verification"]
    artifacts = evidence["artifacts"]
    sharing = evidence["sharing_summary"]

    lines = [
        "# PrivateLabBench Model Claim Evidence Report",
        "",
        "## Claim",
        f"- Text: {claim['text']}",
        f"- Decision metric: {claim['decision_metric']}",
        f"- Direction: {claim['direction']}",
        f"- Minimum lift: {_format_value(claim['minimum_lift'])}",
        "",
        "## Recommendation",
        f"- Recommendation: {decision['recommendation']}",
        f"- Status: {decision['status']}",
    ]
    if decision["reasons"]:
        lines.extend(["- Reasons:"])
        lines.extend([f"  - {reason}" for reason in decision["reasons"]])

    lines.extend([
        "",
        "## Model Under Test",
        f"- Prediction column: `{model['prediction_column']}`",
        f"- Task type: {model['task_type']}",
        f"- Samples: {model['n_samples']}",
        "",
        "### Clean Metrics",
    ])
    lines.extend(_format_lines(model["clean_metrics"]))
    lines.extend(["", "### Reported Metrics"])
    lines.extend(_format_lines(model["reported_metrics"]))

    if baseline:
        lines.extend([
            "",
            "## Baseline",
            f"- Prediction column: `{baseline['prediction_column']}`",
            "",
            "### Baseline Metrics",
        ])
        lines.extend(_format_lines(baseline["metrics"]))

    lines.extend(["", "## Decision Comparison"])
    lines.extend(_format_lines(evidence["comparison"]))

    lines.extend([
        "",
        "## Privacy And Release Gate",
        f"- Privacy summary: {privacy['summary']}",
        f"- Gate status: {privacy['gate_status']}",
        f"- Publishable: {_format_value(privacy['publishable'])}",
    ])
    if privacy.get("risk_level"):
        lines.append(f"- Risk level: {privacy['risk_level']}")

    lines.extend([
        "",
        "## Manifest Verification",
        f"- Valid: {_format_value(verification['valid'])}",
        f"- Reason: {verification['reason']}",
        f"- Report integrity valid: {_format_value(verification['report_valid'])}",
        f"- Artifact hashes valid: {_format_value(verification['artifacts_valid'])}",
        f"- Signature valid: {_format_value(verification.get('signature_valid'))}",
    ])

    lines.extend(["", "## Evidence Artifacts"])
    lines.extend(_format_lines(artifacts))

    lines.extend(["", "## What Stays Local"])
    lines.extend([f"- {item}" for item in sharing["stays_local"]])
    lines.extend(["", "## What Can Be Shared"])
    lines.extend([f"- {item}" for item in sharing["safe_to_share"]])

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _manifest_artifact(kind: str, path: str | Path) -> dict[str, Any]:
    artifact_path = Path(path)
    if not artifact_path.exists():
        raise FileNotFoundError(f"Evidence artifact does not exist: {artifact_path}")
    return {
        "kind": kind,
        "path": str(artifact_path),
        "name": artifact_path.name,
        "sha256": sha256_file(artifact_path),
    }


def write_evidence_manifest(
    output_path: str | Path,
    *,
    evidence: Mapping[str, Any],
    evidence_json_path: str | Path,
    evidence_markdown_path: str | Path,
    source_manifest_path: str | Path,
    signing_secret: str | None = None,
) -> Path:
    evidence_report = json.loads(Path(evidence_json_path).read_text(encoding="utf-8"))
    source_manifest = json.loads(Path(source_manifest_path).read_text(encoding="utf-8"))
    payload = {
        "schema_version": "evidence-manifest/v0.1",
        "project": evidence.get("project"),
        "claim": evidence.get("claim", {}).get("text"),
        "recommendation": evidence.get("decision", {}).get("recommendation"),
        "source_run_id": source_manifest.get("run", {}).get("run_id"),
        "source_run_manifest_id": source_manifest.get("manifest_id"),
        "evidence_report_type": evidence_report.get("report_type"),
        "evidence_report_payload_sha256": evidence_report.get("integrity", {}).get("payload_sha256"),
        "source_run_manifest_sha256": sha256_file(source_manifest_path),
        "artifacts": [
            _manifest_artifact("evidence_json_report", evidence_json_path),
            _manifest_artifact("evidence_markdown_report", evidence_markdown_path),
            _manifest_artifact("source_run_manifest", source_manifest_path),
        ],
    }
    manifest = attach_integrity_metadata(payload, signing_secret=signing_secret)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def verify_evidence_manifest(path: str | Path, *, signing_secret: str | None = None) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    integrity = manifest.get("integrity")
    if not isinstance(integrity, dict):
        return {"valid": False, "reason": "missing_integrity_metadata", "path": str(manifest_path)}

    from privatelabbench.reports.integrity import compute_payload_sha256, sign_payload

    expected_hash = str(integrity.get("payload_sha256", ""))
    actual_hash = compute_payload_sha256(manifest)
    hash_valid = bool(expected_hash) and expected_hash == actual_hash

    signature_valid = None
    if signing_secret:
        expected_signature = str(integrity.get("signature", ""))
        actual_signature = sign_payload(manifest, signing_secret)
        signature_valid = bool(expected_signature) and expected_signature == actual_signature

    artifact_results: list[dict[str, Any]] = []
    artifacts_valid = True
    evidence_report_valid = True
    source_manifest_valid = True
    for artifact in manifest.get("artifacts", []):
        artifact_path = Path(str(artifact.get("path", "")))
        exists = artifact_path.exists()
        actual_artifact_hash = sha256_file(artifact_path) if exists else None
        expected_artifact_hash = artifact.get("sha256")
        valid_hash = exists and actual_artifact_hash == expected_artifact_hash
        result = {
            "kind": artifact.get("kind"),
            "path": str(artifact_path),
            "exists": exists,
            "hash_valid": valid_hash,
            "sha256": actual_artifact_hash,
            "expected_sha256": expected_artifact_hash,
        }
        if artifact.get("kind") == "evidence_json_report" and exists:
            report_check = verify_report(str(artifact_path), signing_secret=signing_secret)
            evidence_report_valid = bool(report_check["valid"])
            result["evidence_report_integrity_valid"] = evidence_report_valid
        if artifact.get("kind") == "source_run_manifest" and exists:
            manifest_check = verify_run_manifest(str(artifact_path), signing_secret=signing_secret)
            source_manifest_valid = bool(manifest_check["valid"])
            result["source_manifest_valid"] = source_manifest_valid
        artifact_results.append(result)
        artifacts_valid = artifacts_valid and bool(valid_hash)

    valid = (
        hash_valid
        and artifacts_valid
        and evidence_report_valid
        and source_manifest_valid
        and signature_valid is not False
    )
    reason = "ok"
    if not hash_valid:
        reason = "evidence_manifest_hash_check_failed"
    elif signature_valid is False:
        reason = "evidence_manifest_signature_check_failed"
    elif not evidence_report_valid:
        reason = "evidence_report_integrity_check_failed"
    elif not source_manifest_valid:
        reason = "source_manifest_check_failed"
    elif not artifacts_valid:
        reason = "artifact_hash_check_failed"
    return {
        "valid": valid,
        "reason": reason,
        "path": str(manifest_path),
        "payload_sha256": actual_hash,
        "expected_payload_sha256": expected_hash,
        "hash_valid": hash_valid,
        "signature_valid": signature_valid,
        "artifacts_valid": artifacts_valid,
        "evidence_report_valid": evidence_report_valid,
        "source_manifest_valid": source_manifest_valid,
        "artifacts": artifact_results,
    }


def run_evidence(
    config_path: str,
    *,
    claim_override: str | None = None,
    markdown_path: str | None = None,
    json_path: str | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    if config.workflow != "predictions":
        raise ValueError("Evidence reports currently support workflow: predictions.")

    claim_cfg = _claim_section(config.raw, claim_override)
    summary = run_config(config_path)
    baseline_column, baseline_metrics = _baseline_evaluation(config)
    candidate_metrics = dict(summary["clean_metrics"])

    decision_metric = str(
        claim_cfg.get("decision_metric")
        or default_decision_metric(str(summary.get("task_type", "")), candidate_metrics)
    )
    direction = str(claim_cfg.get("direction") or infer_metric_direction(decision_metric))
    minimum_lift = float(claim_cfg.get("minimum_lift", 0.0))
    claim_text = str(claim_cfg.get("text") or "Scientific AI model claim evaluation")

    comparison = compare_metric(
        candidate_metrics=candidate_metrics,
        baseline_metrics=baseline_metrics,
        metric=decision_metric,
        direction=direction,
        minimum_lift=minimum_lift,
    )
    manifest_check = verify_run_manifest(summary["manifest"], signing_secret=_signing_secret(config))
    decision = recommendation_from_evidence(
        comparison=comparison,
        privacy_gate_publishable=summary.get("privacy_gate_publishable"),
        manifest_valid=bool(manifest_check["valid"]),
    )

    evidence_result = {
        "project": summary["project"],
        "workflow": summary["workflow"],
        "claim": {
            "text": claim_text,
            "decision_metric": decision_metric,
            "direction": direction,
            "minimum_lift": minimum_lift,
        },
        "model_under_test": {
            "prediction_column": section(config, "input").get("prediction_column"),
            "task_type": summary.get("task_type"),
            "n_samples": summary.get("n_samples"),
            "clean_metrics": summary.get("clean_metrics", {}),
            "reported_metrics": summary.get("reported_metrics", {}),
        },
        "baseline": {
            "prediction_column": baseline_column,
            "metrics": baseline_metrics,
        }
        if baseline_column
        else None,
        "comparison": comparison,
        "privacy": {
            "summary": summary.get("privacy"),
            "gate_status": summary.get("privacy_gate_status"),
            "publishable": summary.get("privacy_gate_publishable"),
            "risk_level": summary.get("privacy_risk_level"),
            "attack_auc": summary.get("privacy_attack_auc"),
            "member_advantage": summary.get("privacy_member_advantage"),
        },
        "decision": decision,
        "verification": {
            "valid": manifest_check["valid"],
            "reason": manifest_check["reason"],
            "report_valid": manifest_check["report_valid"],
            "artifacts_valid": manifest_check["artifacts_valid"],
            "signature_valid": manifest_check["signature_valid"],
            "manifest_payload_sha256": manifest_check["payload_sha256"],
        },
        "artifacts": {
            "evaluation_markdown_report": summary.get("markdown_report"),
            "evaluation_json_report": summary.get("json_report"),
            "audit_log": summary.get("audit_log"),
            "run_manifest": summary.get("manifest"),
            "run_manifest_sha256": summary.get("manifest_sha256"),
        },
        "sharing_summary": _sharing_summary(),
    }

    evidence_json_path = write_json_report(
        json_path or _report_path(config, "evidence_json", f"reports/{config.project}_evidence_report.json"),
        report_type="model_claim_evidence",
        result=evidence_result,
        privacy_config=_privacy_config(config),
        extra={
            "source_run_id": summary.get("run_id"),
            "benchmark_id": summary.get("benchmark_id"),
            "benchmark_version": summary.get("benchmark_version"),
            "benchmark_suite": summary.get("benchmark_suite"),
            "domain": summary.get("domain"),
        },
        config_snapshot=config.raw,
        signing_secret=_signing_secret(config),
    )
    evidence_markdown_path = write_evidence_markdown(
        markdown_path or _report_path(config, "evidence_markdown", f"reports/{config.project}_evidence_report.md"),
        evidence_result,
    )
    evidence_manifest_path = write_evidence_manifest(
        _report_path(config, "evidence_manifest", f"reports/{config.project}_evidence_manifest.json"),
        evidence=evidence_result,
        evidence_json_path=evidence_json_path,
        evidence_markdown_path=evidence_markdown_path,
        source_manifest_path=summary["manifest"],
        signing_secret=_signing_secret(config),
    )
    evidence_manifest_check = verify_evidence_manifest(evidence_manifest_path, signing_secret=_signing_secret(config))
    evidence_json = json.loads(evidence_json_path.read_text(encoding="utf-8"))
    evidence_sha256 = str(evidence_json.get("integrity", {}).get("payload_sha256", ""))

    return {
        "project": config.project,
        "claim": claim_text,
        "recommendation": decision["recommendation"],
        "decision_status": decision["status"],
        "comparison": comparison,
        "privacy_gate_status": summary.get("privacy_gate_status"),
        "manifest_valid": manifest_check["valid"],
        "evidence_markdown_report": str(evidence_markdown_path),
        "evidence_json_report": str(evidence_json_path),
        "evidence_manifest": str(evidence_manifest_path),
        "evidence_manifest_valid": evidence_manifest_check["valid"],
        "evidence_manifest_sha256": sha256_file(evidence_manifest_path),
        "evidence_payload_sha256": evidence_sha256,
        "evidence_json_sha256": sha256_file(evidence_json_path),
        "source_run": summary,
    }


def print_evidence_summary(summary: Mapping[str, Any]) -> None:
    print("PrivateLabBench model claim evidence")
    print(f"Project: {summary['project']}")
    print(f"Claim: {summary['claim']}")
    print(f"Recommendation: {summary['recommendation']}")
    print(f"Decision status: {summary['decision_status']}")
    print(f"Comparison: {summarize_metrics(dict(summary['comparison']))}")
    print(f"Privacy gate: {summary['privacy_gate_status']}")
    print(f"Manifest valid: {str(summary['manifest_valid']).lower()}")
    print(f"Evidence Markdown saved to: {Path(str(summary['evidence_markdown_report']))}")
    print(f"Evidence JSON saved to: {Path(str(summary['evidence_json_report']))}")
    print(f"Evidence manifest saved to: {Path(str(summary['evidence_manifest']))}")
