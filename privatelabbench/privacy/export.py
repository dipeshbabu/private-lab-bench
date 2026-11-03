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
STATUSES = STATUSES | frozenset({"skipped_min_independent_units", "skipped_min_units_per_stratum", "not_supported_missing_cluster_columns", "not_supported_missing_cluster_ids", "not_supported_nonconstant_cluster_strata", "not_supported_crossed_clusters", "not_supported_resource_limit", "not_supported_nested_permutation", "exchangeability_not_declared", "insufficient_valid_permutations", "withheld_small_independent_unit_count", "metric_undefined"})
STAT_ENUMS = {
    "status": STATUSES,
    "method": {"percentile_bootstrap", "paired_percentile_bootstrap", "paired_randomization_swap", "cluster_percentile_bootstrap", "hierarchical_percentile_bootstrap", "paired_cluster_percentile_bootstrap", "paired_hierarchical_percentile_bootstrap", "paired_cluster_randomization_swap"},
    "sampling": {"iid_rows", "stratified_by_target", "independent_clusters", "nested_clusters"},
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
    numbers = {"estimate", "lower", "upper", "valid_resamples", "resamples", "seed", "min_samples", "n_samples", "n_independent_units", "confidence_level", "permutations", "valid_permutations", "p_value", "practical_threshold", "margin"}
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


def _release_statistics(value: Any, policy: Mapping[str, Any]) -> dict[str, Any]:
    result = _statistics(value)
    if "n_independent_units" in result:
        count = result["n_independent_units"]
        if type(count) is not int or count < policy["min_cell_size"]:
            return {"status": "withheld_small_independent_unit_count", **{key: result[key] for key in ("method", "sampling", "metric_basis") if key in result}}
    return result


def validate_policy(value: Any) -> dict[str, Any]:
    policy = dict(_mapping(value))
    allowed = {"schema_version", "id", "enabled", "min_samples", "min_cell_size", "require_privacy_audit", "require_design_audit", "include_design_audit", "include_input_schema", "include_quality_gate", "include_protocol", "include_degradation", "include_slice_inference", "include_multiplicity", "public_validation", "public_shift_features", "public_benchmark", "public_sites", "public_models", "slices", "reviewed_repeat", "review_reference"}
    allowed |= {"public_series", "public_times", "include_source_receipts", "include_submission", "public_submission_ids"}
    if set(policy) - allowed or policy.get("schema_version") != POLICY_SCHEMA:
        raise ValueError("Invalid release policy schema or unknown policy fields")
    _token(policy.get("id"))
    for key in ("enabled", "require_privacy_audit", "require_design_audit", "include_design_audit", "include_input_schema", "include_quality_gate", "include_protocol", "include_degradation", "include_slice_inference", "include_multiplicity", "reviewed_repeat"):
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
    if "public_sites" in policy:
        sites = policy["public_sites"]
        if not isinstance(sites, list) or not sites or len(set(sites)) != len(sites):
            raise ValueError("public_sites must explicitly list unique approved site labels")
        for site in sites:
            _token(site)
    if "public_shift_features" in policy:
        features = policy["public_shift_features"]
        if not isinstance(features, list) or len(set(features)) != len(features):
            raise ValueError("public_shift_features must list unique approved feature aliases")
        for feature in features:
            _token(feature)
    if "public_models" in policy:
        from privatelabbench.aggregate import model_identity
        models = policy["public_models"]
        if not isinstance(models, list) or not models:
            raise ValueError("public_models must explicitly list approved model identities")
        approved_models = [model_identity(item) for item in models]
        if len({(item['id'], item['revision']) for item in approved_models}) != len(models):
            raise ValueError("public_models cannot contain duplicates")
    if "public_validation" in policy:
        from privatelabbench.external_validation import public_approval
        public_approval(policy["public_validation"])
        if not policy.get("include_protocol"):
            raise ValueError("External-validation release requires explicit protocol identity approval")
    if "include_source_receipts" in policy and type(policy["include_source_receipts"]) is not bool:
        raise ValueError("include_source_receipts must be boolean")
    if "include_submission" in policy and type(policy["include_submission"]) is not bool:
        raise ValueError("include_submission must be boolean")
    if "public_submission_ids" in policy:
        values=policy["public_submission_ids"]
        if not isinstance(values,list) or not values or len(set(values))!=len(values):
            raise ValueError("Explicit unique submission IDs are required")
        for value in values: _token(value)
    if "public_series" in policy:
        from privatelabbench.aggregate import model_identity
        model_identity(policy["public_series"])
    if "public_times" in policy:
        from privatelabbench.trends import _time
        values = policy["public_times"]
        if not isinstance(values,list) or not 2 <= len(values) <= 1000:
            raise ValueError("Approve every collection time in chronological order")
        times = [_time(value) for value in values]
        if times != sorted(times) or len(set(times)) != len(times):
            raise ValueError("Approved times must be unique and chronological")
    return policy


def protocol_identity(value: Any) -> dict[str, Any]:
    protocol = _mapping(value)
    from privatelabbench.protocols import ID_PATTERN, VERSION_PATTERN, WITHDRAWN_PROTOCOLS
    if not re.fullmatch(ID_PATTERN, str(protocol.get("id", ""))) or not re.fullmatch(VERSION_PATTERN, str(protocol.get("version", ""))) or not re.fullmatch(r"[0-9a-f]{64}", str(protocol.get("sha256", ""))):
        raise ValueError("An exact, approved evaluation protocol identity is required")
    if f"{protocol['id']}@{protocol['version']}" in WITHDRAWN_PROTOCOLS:
        raise ValueError("Withdrawn protocol; re-evaluate with explicit ordered class labels")
    metrics = protocol.get("metrics")
    if not isinstance(metrics, list) or not metrics or any(metric not in METRICS for metric in metrics) or len(set(metrics)) != len(metrics) or protocol.get("primary_metric") not in metrics:
        raise ValueError("Invalid evaluation protocol metrics")
    return {key: protocol[key] for key in ("id", "version", "sha256", "metrics", "primary_metric")}


def _slice_multiplicity(value: Any, policy: Mapping[str, Any]) -> tuple[dict[Any, Any], dict[str, Any]]:
    if not policy.get("include_multiplicity"):
        return {}, {}
    from privatelabbench.eval.sampling import MultiplicityPolicy, adjust_pvalues
    entries = [(column, label, entry) for column, groups in _mapping(value).items() for label, entry in _mapping(groups).items() if _mapping(entry).get("multiplicity")]
    if not entries:
        return {}, {}
    first = entries[0][2]["multiplicity"]
    selected = MultiplicityPolicy.from_dict({key: first[key] for key in ("schema_version", "method", "family", "alpha", "dependence")})
    approved = {(column, label) for column, labels in policy.get("slices", {}).items() for label in labels}
    probabilities = []
    for column, label, entry in entries:
        declared = entry["multiplicity"]
        if any(declared.get(key) != item for key, item in selected.as_dict().items()):
            raise ValueError("Inconsistent slice test-family declarations")
        test = _mapping(entry.get("randomization_test", {}))
        n_units = test.get("n_independent_units")
        if (column, label) not in approved or type(entry.get("n")) is not int or entry["n"] < policy["min_cell_size"] or n_units is not None and (type(n_units) is not int or n_units < policy["min_cell_size"]):
            return {}, {}
        safe = _release_statistics(test, policy)
        probabilities.append(safe.get("p_value") if safe.get("status") == "evaluated" else None)
    corrected = adjust_pvalues(probabilities, selected)
    output = {(column, label): {**selected.as_dict(), "raw_p_value": raw, "adjusted_p_value": adjusted, "reject": adjusted <= selected.alpha if adjusted is not None else None, "status": "evaluated" if adjusted is not None else "not_testable"} for (column, label, entry), raw, adjusted in zip(entries, probabilities, corrected)}
    metadata = {**selected.as_dict(), "n_tests": len(entries), "n_usable_tests": sum(p is not None for p in probabilities), "n_missing_tests": sum(p is None for p in probabilities), "status": "evaluated" if any(p is not None for p in probabilities) else "not_testable"}
    return output, metadata


def _slices(value: Any, policy: Mapping[str, Any], total: int, *, inference: Any = None) -> dict[str, Any]:
    result = {}
    adjusted, _ = inference if inference is not None else _slice_multiplicity(value, policy)
    for column, approved_labels in policy.get("slices", {}).items():
        groups = {label: entry for label, entry in _mapping(_mapping(value).get(column, {})).items() if not (isinstance(entry, Mapping) and entry.get("n") == 0 and entry.get("status") == "missing_prespecified_slice")}
        # Withhold the whole partition if a complement could reveal a small cell.
        if not groups or set(groups) != set(approved_labels):
            continue
        if any(not isinstance(entry, Mapping) or isinstance(entry.get("n"), bool) or not isinstance(entry.get("n"), int) or entry["n"] < policy["min_cell_size"] for entry in groups.values()):
            continue
        if any("n_independent_units" in entry and (type(entry["n_independent_units"]) is not int or entry["n_independent_units"] < policy["min_cell_size"]) for entry in groups.values()):
            continue
        if sum(entry["n"] for entry in groups.values()) != total:
            continue
        result[column] = {}
        for label, entry in groups.items():
            clean = {"n": entry["n"]}
            if "n_independent_units" in entry:
                clean["n_independent_units"] = entry["n_independent_units"]
            if "metrics" in entry:
                clean["metrics"] = _metrics(entry["metrics"])
            for key in ("metric_a", "metric_b", "improvement"):
                if key in entry:
                    clean[key] = _number(entry[key])
            if "status" in entry:
                if entry["status"] not in STATUSES:
                    raise ValueError("Unknown slice status")
                clean["status"] = entry["status"]
            if policy.get("include_slice_inference"):
                for key in ("paired_interval", "randomization_test", "uncertainty"):
                    if key in entry:
                        clean[key] = _release_statistics(entry[key], policy)
                if entry.get("inference_role") in {"prespecified_critical", "exploratory"}:
                    clean["inference_role"] = entry["inference_role"]
            if (column, label) in adjusted:
                clean["multiplicity"] = adjusted[column, label]
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
        uncertainty = _release_statistics(evaluation.get("uncertainty", {}), policy)
        independent_units = _mapping(evaluation.get("uncertainty", {})).get("n_independent_units")
        if "n_independent_units" in _mapping(evaluation.get("uncertainty", {})) and (type(independent_units) is not int or independent_units < max(policy["min_samples"], policy["min_cell_size"])):
            raise ValueError("Independent-unit count is below release thresholds")
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
        if policy.get("include_protocol") and evaluation.get("protocol"):
            clean["evaluation"]["protocol"] = protocol_identity(evaluation["protocol"])
        if policy.get("include_submission"):
            from privatelabbench.hidden_benchmarks import sanitize_submission
            if not policy.get("include_protocol") or any(not policy.get("public_benchmark",{}).get(key) or policy["public_benchmark"][key]!=shared.get("benchmark",{}).get(key) for key in ("id","version")):
                raise ValueError("Benchmark submissions require exact benchmark and protocol identity approval")
            clean["evaluation"]["benchmark_submission"] = sanitize_submission(evaluation.get("benchmark_submission"),policy)
        if "public_validation" in policy:
            from privatelabbench.external_validation import sanitize_validation
            clean["evaluation"]["external_validation"] = sanitize_validation(evaluation.get("external_validation"), policy["public_validation"])
        if policy.get("include_quality_gate") and evaluation.get("quality_gate"):
            gate = _mapping(evaluation["quality_gate"])
            if gate.get("schema_version") != "quality-gate/v1" or gate.get("status") not in {"pass", "fail", "investigate"}:
                raise ValueError("Invalid quality gate summary")
            clean["evaluation"]["quality_gate"] = {"schema_version": "quality-gate/v1", "status": gate["status"]}
        if policy.get("include_degradation") and evaluation.get("degradation_summary"):
            from privatelabbench.eval.degradation import sanitize_degradation
            clean["evaluation"]["degradation_summary"] = sanitize_degradation(evaluation["degradation_summary"], policy) if mode == "none" else {"status": "withheld_metric_basis_mismatch"}
        if policy.get("include_design_audit"):
            from privatelabbench.design_audit import sanitize_design_audit
            for key in ("design_audit", "reference_design_audit"):
                if evaluation.get(key):
                    clean["evaluation"][key] = sanitize_design_audit(evaluation[key], policy)
    elif schema == "paired-comparison-artifact/v1":
        n = shared.get("n_samples")
        if isinstance(n, bool) or not isinstance(n, int) or n < policy["min_samples"]:
            raise ValueError("Sample count below release threshold")
        independent_units = _mapping(shared.get("paired_interval", {})).get("n_independent_units")
        if "n_independent_units" in _mapping(shared.get("paired_interval", {})) and (type(independent_units) is not int or independent_units < max(policy["min_samples"], policy["min_cell_size"])):
            raise ValueError("Independent-unit count is below release thresholds")
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
            clean[key] = _release_statistics(shared.get(key, {}), policy)
        _, multiplicity = _slice_multiplicity(shared.get("slices", {}), policy)
        if multiplicity and clean["slices"]:
            clean["multiplicity"] = multiplicity
        if policy.get("include_protocol") and shared.get("protocol"):
            clean["protocol"] = protocol_identity(shared["protocol"])
        if policy.get("include_design_audit") and shared.get("design_audits"):
            from privatelabbench.design_audit import sanitize_design_audit
            clean["design_audits"] = [sanitize_design_audit(audit, policy) for audit in shared["design_audits"]]
        identifier = "comparison_id"
    elif schema == "cross-site-aggregate/v1":
        from privatelabbench.aggregate import sanitize_aggregate
        clean = sanitize_aggregate(shared, policy)
        identifier = "aggregate_id"
    elif schema == "longitudinal-series/v1":
        from privatelabbench.trends import sanitize_trend
        clean = sanitize_trend(shared, policy)
        identifier = "series_artifact_id"
    elif schema == "benchmark-leaderboard/v1":
        from privatelabbench.leaderboards import sanitize_leaderboard
        clean = sanitize_leaderboard(shared,policy,_mapping(candidate.get("local",{})).get("protocol_definition"))
        identifier = "leaderboard_id"
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
        evaluation_evidence = _mapping(shared.get("evaluation", {})) if candidate.get("schema_version") == "evaluation-receipt/v1" else {}
        design_evidence = evidence.get("design_audits", [])
        if not isinstance(design_evidence, list):
            raise ValueError("Invalid design-audit evidence")
        comparison_designs = shared.get("design_audits", []) if candidate.get("schema_version") == "paired-comparison-artifact/v1" else []
        if not isinstance(comparison_designs, list): raise ValueError("Invalid paired design evidence")
        design_evidence = [*design_evidence, *comparison_designs, *[evaluation_evidence[key] for key in ("design_audit", "reference_design_audit") if evaluation_evidence.get(key)]]
        from privatelabbench.design_audit import validate_audit_summary
        declared_audits = [validate_audit_summary(audit) for audit in design_evidence]
        if any(audit["status"] == "fail" for audit in declared_audits):
            return ReleaseDecision("deny", ("evaluation_design_failed",), policy_id), None
        if approved.get("require_design_audit") and (not declared_audits or any(audit["status"] != "pass" or not audit["training_reference_present"] or not audit["reference_declared_complete"] for audit in declared_audits)):
            return ReleaseDecision("needs_review", ("required_design_evidence_missing_or_incomplete",), policy_id), None
        if approved.get("require_design_audit") and candidate.get("schema_version") == "paired-comparison-artifact/v1" and {audit.get("model_role") for audit in declared_audits} != {"model_a", "model_b"}:
            return ReleaseDecision("needs_review", ("required_model_specific_design_evidence_missing",), policy_id), None
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
