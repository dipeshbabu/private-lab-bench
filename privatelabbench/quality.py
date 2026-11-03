"""Reproducible model-quality decisions, separate from disclosure permission."""
from __future__ import annotations

import math
from typing import Any, Mapping

from privatelabbench.eval.metrics import METRIC_DIRECTIONS

POLICY_SCHEMA = "quality-policy/v1"
RESULT_SCHEMA = "quality-gate/v1"
EXIT_CODES = {"pass": 0, "fail": 1, "investigate": 2}


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _limits(value: Any, label: str) -> None:
    entry = _object(value, label)
    if not entry or set(entry) - {"min", "max", "min_ci_lower", "max_ci_upper"}:
        raise ValueError(f"{label} needs min/max or min_ci_lower/max_ci_upper")
    if any(not _finite(threshold) for threshold in entry.values()):
        raise ValueError(f"{label} thresholds must be finite numbers")
    if "min" in entry and "max" in entry and entry["min"] > entry["max"]:
        raise ValueError(f"{label}.min cannot exceed max")


def validate_quality_policy(value: Any) -> dict[str, Any]:
    policy = dict(_object(value, "quality policy"))
    if policy.get("schema_version") != POLICY_SCHEMA or set(policy) - {"schema_version", "metric_basis", "min_samples", "metric", "baseline", "comparison", "slices", "privacy"}:
        raise ValueError(f"Expected {POLICY_SCHEMA} and supported policy fields")
    if policy.get("metric_basis", "clean") not in {"clean", "reported"}:
        raise ValueError("metric_basis must be clean or reported")
    if "min_samples" in policy and (isinstance(policy["min_samples"], bool) or not isinstance(policy["min_samples"], int) or policy["min_samples"] < 1):
        raise ValueError("min_samples must be a positive integer")
    metrics = _object(policy.get("metric", {}), "metric")
    for name, limits in metrics.items():
        if name not in METRIC_DIRECTIONS:
            raise ValueError(f"Unsupported quality metric: {name}")
        _limits(limits, f"metric.{name}")
    baseline = _object(policy.get("baseline", {}), "baseline")
    if baseline:
        if set(baseline) - {"metric", "allow_relative_regression", "allow_absolute_regression"} or baseline.get("metric") not in METRIC_DIRECTIONS or not set(baseline) & {"allow_relative_regression", "allow_absolute_regression"}:
            raise ValueError("baseline requires a supported metric and a regression allowance")
        for key in ("allow_relative_regression", "allow_absolute_regression"):
            if key in baseline and (not _finite(baseline[key]) or baseline[key] < 0):
                raise ValueError("Regression allowances must be finite and nonnegative")
    comparison = _object(policy.get("comparison", {}), "comparison")
    if comparison and (set(comparison) - {"min_improvement", "require_confident"} or "min_improvement" not in comparison or not _finite(comparison["min_improvement"]) or not isinstance(comparison.get("require_confident", False), bool)):
        raise ValueError("comparison needs finite min_improvement and optional boolean require_confident")
    slices = _object(policy.get("slices", {}), "slices")
    for key, threshold in slices.items():
        if key == "critical":
            if not threshold:
                raise ValueError("Critical slices must contain at least one rule")
            for alias, entry in _object(threshold, "critical slices").items():
                entry = _object(entry, f"critical.{alias}")
                if not isinstance(entry.get("column"), str) or not isinstance(entry.get("value"), str):
                    raise ValueError("Critical slices require explicit column and value")
                if set(entry) - {"column", "value", "metric", "min", "max", "min_ci_lower", "max_ci_upper"} or entry.get("metric") not in METRIC_DIRECTIONS:
                    raise ValueError("Critical slice requires a supported metric")
                _limits({k: v for k, v in entry.items() if k not in {"column", "value", "metric"}}, f"critical.{alias}")
        else:
            parts = key.split("_")
            if len(parts) < 3 or parts[0] != "worst" or "_".join(parts[1:-1]) not in METRIC_DIRECTIONS or parts[-1] not in {"min", "max"} or not _finite(threshold):
                raise ValueError("Worst-slice fields use worst_<metric>_min/max and a finite threshold")
    privacy = _object(policy.get("privacy", {}), "privacy")
    if set(privacy) - {"require_audit", "require_release", "max_level"}:
        raise ValueError("Unsupported privacy quality requirement")
    if any(not isinstance(privacy[key], bool) for key in ("require_audit", "require_release") if key in privacy):
        raise ValueError("Privacy requirements must be boolean")
    if "max_level" in privacy and privacy["max_level"] not in {"low", "moderate", "high"}:
        raise ValueError("Privacy max_level must be low, moderate, or high")
    if not metrics and not baseline and not comparison and not slices and not any(privacy.values()) and "min_samples" not in policy:
        raise ValueError("A quality policy must contain at least one decision rule")
    return policy


def _evidence(artifact: Mapping[str, Any], basis: str) -> dict[str, Any]:
    if artifact.get("schema_version") == "evaluation-receipt/v1":
        shared = artifact.get("shareable", {})
        evaluation = shared.get("evaluation", {})
        local = artifact.get("local", {}) if artifact.get("scope") == "local" else {}
        mode = shared.get("privacy", {}).get("mechanism", {}).get("mode", "none")
        metrics = local.get("exact_metrics", {}) if basis == "clean" and local else evaluation.get("metrics", {})
        if basis == "clean" and not local and mode != "none":
            metrics = {}
        return {"metrics": metrics, "baseline": local.get("baseline_metrics", {}), "uncertainty": local.get("uncertainty", evaluation.get("uncertainty", {})), "slices": evaluation.get("slices", {}), "n": evaluation.get("sample_counts", {}).get("n_samples", evaluation.get("sample_counts", {}).get("total_samples")), "privacy": shared.get("privacy", {}), "mode": mode}
    if artifact.get("schema_version") == "paired-comparison-artifact/v1":
        comparison = artifact.get("shareable", {})
        return {"metrics": comparison.get("model_a", {}).get("metrics", {}), "baseline": comparison.get("model_b", {}).get("metrics", {}), "n": comparison.get("n_samples"), "comparison": comparison, "slices": {}, "uncertainty": {}, "privacy": {}, "mode": "none"}
    result = artifact.get("result", {})
    return {"metrics": result.get("clean_metrics", result.get("aggregate_clean_metrics", {})) if basis == "clean" else result.get("reported_metrics", result.get("aggregate_reported_metrics", {})), "baseline": result.get("baseline_metrics", {}), "uncertainty": result.get("uncertainty", {}), "slices": result.get("slice_metrics", {}), "n": result.get("n_samples", result.get("total_samples")), "privacy": {"audits": {"membership_inference": result.get("privacy_risk", {})}, "release": result.get("privacy_gate", result.get("aggregate_release", {}))}, "mode": artifact.get("privacy", {}).get("mode", "none")}


def evaluate_quality_gate(artifact: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    policy = validate_quality_policy(policy)
    basis = policy.get("metric_basis", "clean")
    evidence = _evidence(_object(artifact, "artifact"), basis)
    rules: list[dict[str, Any]] = []

    def rule(name: str, observed: Any, threshold: Any, operator: str, missing: str = "evidence_missing") -> None:
        valid = _finite(observed)
        passes = valid and (observed <= threshold if operator == "max" else observed >= threshold)
        rules.append({"name": name, "status": "pass" if passes else "fail" if valid else "investigate", "observed": observed if valid else None, "operator": operator, "threshold": threshold, "reason": "threshold_met" if passes else "threshold_violated" if valid else missing})

    def limits(name: str, metric: str, entries: Mapping[str, Any], metrics: Mapping[str, Any], uncertainty: Mapping[str, Any]) -> None:
        for bound, threshold in entries.items():
            value = metrics.get(metric)
            reason = "metric_missing_or_undefined"
            if bound in {"min_ci_lower", "max_ci_upper"}:
                interval = uncertainty.get("metrics", {}).get(metric, {})
                compatible = uncertainty.get("metric_basis", "clean_metrics") == ("clean_metrics" if basis == "clean" or evidence["mode"] == "none" else "reported_metrics")
                value = interval.get("lower" if bound == "min_ci_lower" else "upper") if compatible and interval.get("status") == "evaluated" else None
                reason = "uncertainty_missing_or_incompatible"
            rule(f"{name}.{bound}", value, threshold, "min" if bound.startswith("min") else "max", reason)

    if "min_samples" in policy:
        rule("min_samples", evidence["n"], policy["min_samples"], "min")
    for metric, entries in policy.get("metric", {}).items():
        limits(f"metric.{metric}", metric, entries, evidence["metrics"], evidence["uncertainty"])
    baseline = policy.get("baseline", {})
    if baseline:
        metric = baseline["metric"]
        candidate, reference = evidence["metrics"].get(metric), evidence["baseline"].get(metric)
        regression = (candidate - reference) * (1 if METRIC_DIRECTIONS[metric] == "lower_is_better" else -1) if _finite(candidate) and _finite(reference) else None
        if "allow_absolute_regression" in baseline:
            rule("baseline.absolute_regression", regression, baseline["allow_absolute_regression"], "max")
        if "allow_relative_regression" in baseline:
            relative = regression / abs(reference) if regression is not None and reference != 0 else None
            rule("baseline.relative_regression", relative, baseline["allow_relative_regression"], "max", "baseline_missing_undefined_or_zero")
    comparison = policy.get("comparison", {})
    if comparison:
        paired = evidence.get("comparison", {})
        interval = paired.get("paired_interval", {})
        if comparison.get("require_confident"):
            observed = interval.get("lower") if interval.get("status") == "evaluated" else None
        else:
            observed = paired.get("improvement_a_over_b")
        rule("comparison.improvement", observed, comparison["min_improvement"], "min", "paired_evidence_missing_or_underpowered")
    for key, threshold in policy.get("slices", {}).items():
        if key == "critical":
            for alias, entry in threshold.items():
                group = evidence["slices"].get(entry["column"], {}).get(entry["value"], {})
                usable = group.get("status") == "evaluated" and (basis == "clean" or evidence["mode"] == "none")
                limits(f"slice.{alias}", entry["metric"], {k: v for k, v in entry.items() if k not in {"column", "value", "metric"}}, group.get("metrics", {}) if usable else {}, group.get("uncertainty", {}))
        else:
            metric, operator = key[len("worst_"):].rsplit("_", 1)
            groups = [group for partition in evidence["slices"].values() for group in partition.values()]
            available = bool(groups) and all(group.get("status") == "evaluated" and _finite(group.get("metrics", {}).get(metric)) for group in groups) and (basis == "clean" or evidence["mode"] == "none")
            worst = max if METRIC_DIRECTIONS[metric] == "lower_is_better" else min
            extreme = worst(group["metrics"][metric] for group in groups) if available else None
            rule(f"slices.{key}", extreme, threshold, operator, "slice_missing_suppressed_or_undefined")
    privacy = evidence["privacy"]
    audits = privacy.get("audits", {})
    audit = audits.get("membership_inference", {})
    for name, wanted in policy.get("privacy", {}).items():
        if name == "require_audit" and wanted:
            ran = audit.get("risk_level") in {"low", "moderate", "high"} or audits.get("status") == "pass_under_policy"
            rule("privacy.audit", 1 if ran else None, 1, "min", "privacy_audit_not_run_or_inconclusive")
        elif name == "require_release" and wanted:
            release = privacy.get("release", {})
            observed = 1 if release.get("status") == "pass" and release.get("publishable") is True else 0 if release.get("status") in {"fail", "deny", "blocked"} else None
            rule("privacy.release_gate", observed, 1, "min", "release_gate_missing")
        elif name == "max_level":
            ranks = {"low": 0, "moderate": 1, "high": 2}
            rule("privacy.risk_level", ranks.get(audit.get("risk_level")), ranks[wanted], "max", "risk_level_not_disclosed")
    if not rules:
        raise ValueError("A quality policy must contain at least one decision rule")
    status = "fail" if any(item["status"] == "fail" for item in rules) else "investigate" if any(item["status"] == "investigate" for item in rules) else "pass"
    return {"schema_version": RESULT_SCHEMA, "status": status, "metric_basis": basis, "rules": rules, "policy": policy, "scope": "local", "limitations": ["Thresholds are user policy, not universal scientific validity.", "Missing or suppressed evidence cannot satisfy a rule.", "Quality gates do not authorize disclosure."]}
