"""Fail-closed, local-only disclosure boundary for aggregate artifacts.

This is disclosure policy enforcement, not differential privacy or an upload API.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

from privatelabbench.reports.integrity import attach_integrity_metadata

POLICY_SCHEMA = "release-policy/v1"
METRICS = frozenset({"mae", "rmse", "r2", "accuracy", "f1", "auroc", "macro_f1", "weighted_f1", "log_loss", "macro_auroc_ovr"})
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@+-]{0,127}\Z")
STATUSES = frozenset({"evaluated", "undefined_point_estimate", "insufficient_valid_resamples", "skipped_min_samples", "skipped_min_slice_size", "unavailable", "disabled", "inconclusive", "insufficient_evidence", "a_noninferior", "noninferiority_not_established", "withheld_metric_basis_mismatch"})
STAT_ENUMS = {
    "status": STATUSES,
    "method": {"percentile_bootstrap", "paired_percentile_bootstrap", "paired_randomization_swap"},
    "sampling": {"iid_rows", "stratified_by_target"},
    "metric_basis": {"clean_metrics", "reported_metrics"},
    "released_metric_basis": {"reported_metrics"},
    "point_estimate": {"a_above_threshold", "b_above_threshold", "below_practical_threshold"},
    "confidence_interval": {"a_exceeds_threshold", "b_exceeds_threshold", "inconclusive", "insufficient_evidence"},
}


@dataclass(frozen=True)
class ReleaseDecision:
    decision: str
    reason_codes: tuple[str, ...]
    policy_id: str | None = None
    schema_version: str = POLICY_SCHEMA
    audience: str = "external"
    audit_status: str = "not_run"
    excluded_fields: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Expected an object")
    return value


def _token(value: Any) -> str:
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise ValueError("Public labels must be short identifiers, without paths or free text")
    return value


def _number(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Aggregate values must be numeric")
    return value if math.isfinite(value) else None


def _metrics(value: Any) -> dict[str, Any]:
    return {key: _number(item) for key, item in _mapping(value).items() if key in METRICS}


def _statistics(value: Any) -> dict[str, Any]:
    """Allowlisted scalar uncertainty/decision fields; never copy plugin dictionaries."""
    strings = {"status", "method", "sampling", "metric_basis", "released_metric_basis", "point_estimate", "confidence_interval"}
    numbers = {"estimate", "lower", "upper", "valid_resamples", "resamples", "seed", "min_samples", "n_samples", "confidence_level", "permutations", "p_value", "practical_threshold", "margin"}
    output = {}
    for key, item in _mapping(value).items():
        if key in strings:
            if item not in STAT_ENUMS[key]:
                raise ValueError("Unknown statistical metadata")
            output[key] = item
        elif key in numbers:
            output[key] = _number(item)
        elif key in {"enabled", "include_slices"} and isinstance(item, bool):
            output[key] = item
        elif key == "schema_version" and item == "uncertainty/v1":
            output[key] = item
        elif key == "metrics":
            output[key] = {name: _statistics(interval) for name, interval in _mapping(item).items() if name in METRICS}
        elif key == "noninferiority" and isinstance(item, Mapping):
            output[key] = _statistics(item)
    return output


def validate_policy(value: Any) -> dict[str, Any]:
    policy = dict(_mapping(value))
    allowed = {"schema_version", "id", "enabled", "min_samples", "min_cell_size", "require_privacy_audit", "include_input_schema", "include_quality_gate", "public_benchmark", "slices", "reviewed_repeat", "review_reference"}
    if set(policy) - allowed or policy.get("schema_version") != POLICY_SCHEMA:
        raise ValueError("Invalid release policy schema or unknown policy fields")
    _token(policy.get("id"))
    for key in ("enabled", "require_privacy_audit", "include_input_schema", "include_quality_gate", "reviewed_repeat"):
        if key in policy and not isinstance(policy[key], bool):
            raise ValueError(f"{key} must be boolean")
    for key, default in (("min_samples", 20), ("min_cell_size", 5)):
        count = policy.setdefault(key, default)
        if isinstance(count, bool) or not isinstance(count, int) or count < 2:
            raise ValueError(f"{key} must be an integer of at least 2")
    slices = _mapping(policy.get("slices", {}))
    if len(slices) > 1:
        raise ValueError("Only one disjoint slice partition may be released")
    for column, labels in slices.items():
        _token(column)
        if not isinstance(labels, list) or not labels or len(set(labels)) != len(labels):
            raise ValueError("Slice labels must be an explicit unique list")
        for label in labels:
            _token(label)
    for key, item in _mapping(policy.get("public_benchmark", {})).items():
        if key not in {"id", "version", "suite", "domain", "protocol"}:
            raise ValueError("Unknown public benchmark field")
        if key == "protocol" and item == "prediction-table/v1":
            continue
        _token(item)
    if policy.get("reviewed_repeat"):
        _token(policy.get("review_reference"))
    return policy


def _slices(value: Any, policy: Mapping[str, Any], total: int) -> dict[str, Any]:
    result = {}
    for column, approved_labels in policy.get("slices", {}).items():
        groups = _mapping(_mapping(value).get(column, {}))
        # Withhold the whole partition if a complement could reveal a small cell.
        if not groups or set(groups) != set(approved_labels):
            continue
        if any(not isinstance(entry, Mapping) or isinstance(entry.get("n"), bool) or not isinstance(entry.get("n"), int) or entry["n"] < policy["min_cell_size"] for entry in groups.values()):
            continue
        if sum(entry["n"] for entry in groups.values()) != total:
            continue
        result[column] = {}
        for label, entry in groups.items():
            clean = {"n": entry["n"]}
            if "metrics" in entry:
                clean["metrics"] = _metrics(entry["metrics"])
            for key in ("metric_a", "metric_b", "improvement"):
                if key in entry:
                    clean[key] = _number(entry[key])
            if "status" in entry:
                if entry["status"] not in STATUSES:
                    raise ValueError("Unknown slice status")
                clean["status"] = entry["status"]
            result[column][label] = clean
    return result


def _sanitize(candidate: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    shared = _mapping(candidate.get("shareable"))
    schema = candidate.get("schema_version")
    if schema == "evaluation-receipt/v1":
        evaluation = _mapping(shared.get("evaluation"))
        source = evaluation.get("metric_source")
        if source not in {"reported_metrics", "aggregate_reported_metrics"}:
            raise ValueError("Only explicitly reported metrics may be released")
        counts = {key: item for key, item in _mapping(evaluation.get("sample_counts")).items() if key in {"n_samples", "n_train", "n_test", "n_clients", "total_samples"}}
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in counts.values()):
            raise ValueError("Invalid sample counts")
        n = counts.get("n_samples", counts.get("total_samples"))
        if n is None or n < policy["min_samples"] or any(item < policy["min_cell_size"] for key, item in counts.items() if key not in {"n_clients", "n_samples", "total_samples"}):
            raise ValueError("Sample count below release threshold")
        input_schema = _mapping(evaluation.get("input_schema"))
        clean_schema = {"schema_version": "prediction-table/v1" if input_schema.get("schema_version") == "prediction-table/v1" else "legacy-task-input/v1"}
        if policy.get("include_input_schema", False):
            for key in ("sample_id_column", "target_column", "split_column", "sample_id_status"):
                if key in input_schema:
                    clean_schema[key] = _token(input_schema[key]) if input_schema[key] is not None else None
            for key in ("prediction_columns", "metadata_columns", "slice_columns", "class_labels"):
                if key in input_schema:
                    values = input_schema[key]
                    if not isinstance(values, list):
                        raise ValueError("Invalid input schema")
                    clean_schema[key] = [_token(item) for item in values]
        privacy = _mapping(shared.get("privacy"))
        mechanism = _mapping(privacy.get("mechanism", {}))
        mode = mechanism.get("mode", "none")
        if mode not in {"none", "metric_perturbation"}:
            raise ValueError("Unsupported release mechanism")
        uncertainty = _statistics(evaluation.get("uncertainty", {}))
        if mode != "none" and uncertainty.get("metric_basis") == "clean_metrics":
            uncertainty = {"status": "withheld_metric_basis_mismatch", "metric_basis": "clean_metrics", "released_metric_basis": "reported_metrics"}
        task_type = evaluation.get("task_type")
        if task_type not in {"regression", "classification", "multiclass", None}:
            raise ValueError("Unknown task type")
        clean = {
            "run": {"run_id": None, "created_at": None, "project": None, "task": "predictions" if clean_schema["schema_version"] == "prediction-table/v1" else None, "report_type": "evaluation"},
            "benchmark": dict(policy.get("public_benchmark", {})),
            "evaluation": {"task_type": task_type, "sample_counts": counts, "input_schema": clean_schema, "metrics": _metrics(evaluation.get("metrics")), "metric_source": source, "uncertainty": uncertainty, "slices": _slices(evaluation.get("slices", {}), policy, n) if mode == "none" else {}},
            "privacy": {"mechanism": {"mode": mode, "formal_dp": False, "guarantee_level": "none" if mode == "none" else "heuristic_no_dp_guarantee"}, "audits": {}, "release": {}},
            "provenance": {"package": {"name": "private-lab-bench"}},
            "artifacts": [],
        }
        identifier = "receipt_id"
        if policy.get("include_quality_gate") and evaluation.get("quality_gate"):
            gate = _mapping(evaluation["quality_gate"])
            if gate.get("schema_version") != "quality-gate/v1" or gate.get("status") not in {"pass", "fail", "investigate"}:
                raise ValueError("Invalid quality gate summary")
            clean["evaluation"]["quality_gate"] = {"schema_version": "quality-gate/v1", "status": gate["status"]}
    elif schema == "paired-comparison-artifact/v1":
        n = shared.get("n_samples")
        if isinstance(n, bool) or not isinstance(n, int) or n < policy["min_samples"]:
            raise ValueError("Sample count below release threshold")
        metric = shared.get("metric")
        if metric not in METRICS:
            raise ValueError("Unsupported comparison metric")
        if shared.get("task_type") not in {"regression", "classification", "multiclass"} or shared.get("direction") not in {"lower_is_better", "higher_is_better"}:
            raise ValueError("Invalid comparison semantics")
        clean = {"n_samples": n, "metric": metric, "task_type": shared["task_type"], "direction": shared["direction"], "class_labels": [], "sample_id_column": None, "target_column": None, "comparison_schema": "paired-comparison/v1", "alignment": {"status": "exact_sample_id_match", "n_model_a": n, "n_model_b": n, "dropped_samples": 0}, "slices": _slices(shared.get("slices", {}), policy, n)}
        for key in ("raw_delta_a_minus_b", "improvement_a_over_b"):
            clean[key] = _number(shared.get(key))
            if clean[key] is None:
                raise ValueError("Undefined comparison estimate")
        for key in ("model_a", "model_b"):
            model = _mapping(shared.get(key))
            clean[key] = {"name": key, "metrics": _metrics(model.get("metrics")), "selected_metric": _number(model.get("selected_metric"))}
            if clean[key]["selected_metric"] is None:
                raise ValueError("Undefined selected metric")
        for key in ("paired_interval", "randomization_test", "decision"):
            clean[key] = _statistics(shared.get(key, {}))
        identifier = "comparison_id"
    else:
        raise ValueError("Unsupported export schema")
    if not clean.get("evaluation", clean).get("metrics", clean.get("metric")):
        raise ValueError("No supported metrics to release")
    # Fresh identifiers reveal neither paths nor caller-supplied free-form IDs.
    from uuid import uuid4
    from datetime import datetime, timezone
    return {"schema_version": schema, identifier: str(uuid4()), "created_at": datetime.now(timezone.utc).isoformat(), "scope": "shareable", "shareable": clean}


def check_release(candidate: Any, policy: Any, *, evidence: Any = None) -> tuple[ReleaseDecision, dict[str, Any] | None]:
    if policy is None:
        return ReleaseDecision("needs_review", ("missing_policy",)), None
    try:
        approved = validate_policy(policy)
    except (ValueError, TypeError):
        return ReleaseDecision("needs_review", ("invalid_policy",)), None
    policy_id = approved["id"]
    if approved.get("enabled") is not True:
        return ReleaseDecision("deny", ("release_disabled",), policy_id), None
    try:
        candidate = _mapping(candidate)
        shared = _mapping(candidate.get("shareable"))
        privacy = _mapping(shared.get("privacy", {}))
        evidence = _mapping(evidence if evidence is not None else privacy)
        gates = evidence.get("gates", [privacy.get("release", {})])
        if not isinstance(gates, list):
            raise ValueError("Invalid gate evidence")
        for gate in gates:
            gate = _mapping(gate)
            if gate and (gate.get("status") != "pass" or gate.get("publishable") is not True):
                return ReleaseDecision("deny", ("upstream_release_gate_not_passed",), policy_id, audit_status="blocked"), None
        audit = evidence.get("audit", _mapping(privacy.get("audits", {})).get("membership_inference"))
        audit_status = "not_run"
        if audit:
            audit = _mapping(audit)
            audit_status = "pass_under_policy" if audit.get("risk_level") in {"low", "moderate", "high"} else "inconclusive"
        if approved.get("require_privacy_audit", True) and audit_status != "pass_under_policy":
            return ReleaseDecision("needs_review", ("required_privacy_evidence_missing",), policy_id, audit_status=audit_status), None
        output = _sanitize(candidate, approved)
        clean = output["shareable"]
        decision = ReleaseDecision("allow", ("explicit_policy_passed",), policy_id, audit_status=audit_status, excluded_fields=("local", "free_form_metadata", "artifact_names_and_hashes", "unapproved_slices", "plugin_fields"))
        if "privacy" in clean:
            clean["privacy"]["release"] = {"status": "pass", "publishable": True, **decision.as_dict()}
            clean["privacy"]["audits"] = {"status": audit_status}
        else:
            clean["release"] = decision.as_dict()
        json.dumps(output, allow_nan=False)
        return decision, output
    except (ValueError, TypeError, KeyError, OverflowError):
        return ReleaseDecision("needs_review", ("invalid_candidate_or_insufficient_counts",), policy_id), None


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".plb-", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def publish_shareable_artifact(candidate: Any, policy: Any, path: str | Path, *, evidence: Any = None, signing_secret: str | None = None, signer: Mapping[str, Any] | None = None) -> ReleaseDecision:
    """The sole shareable JSON writer. Denial removes any previous export."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    decision, payload = check_release(candidate, policy, evidence=evidence)
    audit_path = output.with_suffix(".release-audit.json")
    if payload is not None:
        ledger_path = output.parent / ".plb-release-ledger.json"
        lock_path = output.parent / ".plb-release.lock"
        lock = None
        try:
            lock = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
            if not isinstance(ledger, dict):
                raise ValueError("Invalid local release ledger")
            digest = hashlib.sha256(json.dumps(payload["shareable"], sort_keys=True, allow_nan=False).encode()).hexdigest()
            previous = ledger.get(decision.policy_id)
            if previous is not None and previous != digest and not policy.get("reviewed_repeat", False):
                decision = ReleaseDecision("needs_review", ("changed_repeated_release_requires_review",), decision.policy_id)
            else:
                # Record approval first: a failed export conservatively retains it.
                ledger[decision.policy_id] = digest
                atomic_write_json(ledger_path, ledger)
                if signer is not None:
                    from privatelabbench.reports.trust import sign_artifact
                    artifact = sign_artifact(payload, signer)
                else:
                    artifact = attach_integrity_metadata(payload, signing_secret=signing_secret)
                atomic_write_json(output, artifact)
        except (OSError, ValueError, TypeError):
            output.unlink(missing_ok=True)
            decision = ReleaseDecision("needs_review", ("release_storage_or_lock_failed",), decision.policy_id)
        finally:
            if lock is not None:
                os.close(lock)
                lock_path.unlink(missing_ok=True)
    audit = {"schema_version": "release-audit/v1", "scope": "local", **decision.as_dict()}
    if isinstance(policy, Mapping) and policy.get("reviewed_repeat"):
        audit["reviewed_repeat"] = True
        audit["review_reference"] = policy.get("review_reference")
    try:
        atomic_write_json(audit_path, audit)
    except OSError:
        output.unlink(missing_ok=True)
        raise
    return decision
