"""Local longitudinal evidence from verified, already-shareable receipts."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from privatelabbench.aggregate import model_identity
from privatelabbench.eval.metrics import METRIC_DIRECTIONS
from privatelabbench.privacy.export import _mapping, _token, protocol_identity
from privatelabbench.reports.integrity import attach_integrity_metadata, verify_payload
from privatelabbench.reports.receipt import validate_receipt_shape

SCHEMA = "longitudinal-series/v1"


def _finite(value):
    return (
        float(value) if type(value) in {float, int} and math.isfinite(value) else None
    )


def _time(value):
    if not isinstance(value, str):
        raise ValueError(
            "Each receipt requires an explicit ISO date or timezone-aware timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if len(value) == 10:
            parsed = parsed.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None:
            raise ValueError("Timestamps require a timezone")
        return (
            parsed.astimezone(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
    except ValueError as exc:
        raise ValueError("Use an ISO date or timezone-aware timestamp") from exc


def _interval(value, metric, point, *, mode="none"):
    if (
        mode != "none"
        or not isinstance(value, Mapping)
        or value.get("metric_basis", "clean_metrics") != "clean_metrics"
    ):
        return None
    if not isinstance(value.get("metrics"), Mapping):
        return None
    entry = value["metrics"].get(metric, {})
    if not isinstance(entry, Mapping):
        return None
    lower, upper = _finite(entry.get("lower")), _finite(entry.get("upper"))
    level = _finite(value.get("confidence_level"))
    estimate = _finite(entry.get("estimate"))
    if (
        entry.get("status") != "evaluated"
        or lower is None
        or upper is None
        or lower > upper
        or level is None
        or not 0 < level < 1
        or estimate is None
        or point is None
        or not math.isclose(estimate, point, rel_tol=1e-10, abs_tol=1e-12)
    ):
        return None
    return {"lower": lower, "upper": upper, "confidence_level": level}


def _change(reference, current, metric, threshold):
    a, b = reference["estimate"], current["estimate"]
    delta = b - a if a is not None and b is not None else None
    sign = 1 if METRIC_DIRECTIONS[metric] == "lower_is_better" else -1
    degradation = sign * delta if delta is not None else None
    bounds = None
    if reference.get("interval") and current.get("interval"):
        x, y = reference["interval"], current["interval"]
        lower, upper = y["lower"] - x["upper"], y["upper"] - x["lower"]
        if sign < 0:
            lower, upper = -upper, -lower
        bounds = {
            "lower": lower,
            "upper": upper,
            "marginal_coverage_union_bound": max(
                0.0, x["confidence_level"] + y["confidence_level"] - 1
            ),
            "method": "difference_of_marginal_bounds",
            "joint_resampling": False,
        }
    if reference is current and delta is not None:
        bounds = {
            "lower": 0.0,
            "upper": 0.0,
            "marginal_coverage_union_bound": 1.0,
            "method": "identical_reference",
            "joint_resampling": False,
        }
    practical = (
        "unavailable"
        if degradation is None
        else (
            "degradation"
            if degradation > threshold
            else "improvement"
            if degradation < -threshold
            else "within_threshold"
        )
    )
    uncertainty = (
        "unavailable"
        if bounds is None
        else (
            "bounds_exclude_threshold"
            if bounds["lower"] > threshold
            else (
                "bounds_exclude_negative_threshold"
                if bounds["upper"] < -threshold
                else "compatible_with_no_material_change"
            )
        )
    )
    return {
        "raw_delta": delta,
        "degradation": degradation,
        "relative_degradation": (
            degradation / abs(a) if degradation is not None and a else None
        ),
        "practical_threshold": threshold,
        "point_change": practical,
        "uncertainty_assessment": uncertainty,
        "difference_bounds": bounds,
    }


def _record(evaluation, shared, time, metric, mode, quality):
    for key in ("sample_counts", "metrics", "uncertainty", "slices"):
        _mapping(evaluation.get(key, {}))
    n = evaluation.get("sample_counts", {}).get("n_samples")
    if type(n) is not int or n < 2:
        raise ValueError("Every period needs an explicit sample count of at least two")
    estimate = _finite(evaluation.get("metrics", {}).get(metric))
    units = evaluation.get("uncertainty", {}).get("n_independent_units")
    if units is not None and (type(units) is not int or not 2 <= units <= n):
        raise ValueError("Invalid released independent-unit count")
    slices = {}
    for column, groups in evaluation.get("slices", {}).items():
        _token(column)
        if not isinstance(groups, Mapping):
            raise ValueError("Invalid released slice partition")
        slices[column] = {}
        for label, group in groups.items():
            _token(label)
            if not isinstance(group, Mapping):
                raise ValueError("Invalid released slice metrics")
            count = group.get("n_samples")
            if type(count) is not int or count < 0 or count > n:
                raise ValueError("Invalid released slice count")
            point = (
                _finite(group.get("metrics", {}).get(metric))
                if group.get("status") == "evaluated"
                else None
            )
            slice_units = _mapping(group.get("uncertainty", {})).get(
                "n_independent_units"
            )
            if slice_units is not None and (
                type(slice_units) is not int or not 2 <= slice_units <= count
            ):
                raise ValueError("Invalid released slice independent-unit count")
            slices[column][label] = {
                "n_samples": count,
                "n_independent_units": slice_units,
                "estimate": point,
                "interval": _interval(
                    group.get("uncertainty"), metric, point, mode=mode
                ),
            }
    gate = quality or evaluation.get("quality_gate", {})
    status = gate.get("status") if isinstance(gate, Mapping) else None
    if status not in {None, "pass", "fail", "investigate"}:
        raise ValueError("Unknown period quality-gate status")
    # Existing cohort diagnostics remain evidence from that run, not an invented cross-period test.
    diagnostic = evaluation.get("degradation_summary", {})
    diagnostic = diagnostic if isinstance(diagnostic, Mapping) else {}
    diagnostic_status = (
        "available_in_source_receipt"
        if diagnostic.get("schema_version") == "degradation-summary/v1"
        else "not_in_source_receipt"
    )
    return {
        "time": time,
        "n_samples": n,
        "n_independent_units": units,
        "estimate": estimate,
        "interval": _interval(
            evaluation.get("uncertainty"), metric, estimate, mode=mode
        ),
        "slices": slices,
        "quality_gate": status or "not_available",
        "cohort_diagnostics": diagnostic_status,
    }


def _summarize(records, metric, reference, threshold, prevalence_threshold, critical):
    output = []
    base = records[reference]
    for index, row in enumerate(records):
        period = {
            **row,
            "from_reference": _change(base, row, metric, threshold),
            "from_previous": (
                _change(records[index - 1], row, metric, threshold) if index else None
            ),
            "slice_changes": [],
        }
        for column in sorted(set(base["slices"]) | set(row["slices"])):
            a, b = base["slices"].get(column, {}), row["slices"].get(column, {})
            for label in sorted(set(a) | set(b)):
                before, after = a.get(label), b.get(label)
                prior_prevalence = (
                    before["n_samples"] / base["n_samples"] if before else 0.0
                )
                current_prevalence = (
                    after["n_samples"] / row["n_samples"] if after else 0.0
                )
                change = (
                    _change(before, after, metric, threshold)
                    if before and after
                    else None
                )
                period["slice_changes"].append(
                    {
                        "column": column,
                        "value": label,
                        "critical": [column, label] in critical,
                        "presence": (
                            "both"
                            if before and after
                            else "new"
                            if after
                            else "missing"
                        ),
                        "prevalence_change": current_prevalence - prior_prevalence,
                        "material_prevalence_change": abs(
                            current_prevalence - prior_prevalence
                        )
                        >= prevalence_threshold,
                        "from_reference": change,
                    }
                )
        period["largest_degradations"] = sorted(
            [
                item
                for item in period["slice_changes"]
                if item["from_reference"]
                and item["from_reference"]["degradation"] is not None
                and item["from_reference"]["degradation"] > threshold
            ],
            key=lambda item: item["from_reference"]["degradation"],
            reverse=True,
        )
        output.append(period)
    return output


def trend_receipts(
    paths,
    *,
    times,
    series,
    model,
    metric=None,
    reference=0,
    practical_threshold=0.0,
    prevalence_threshold=0.1,
    critical_slices=(),
    quality_policy=None,
    signing_secret=None,
    trust_store=None,
    require_trusted_signer=False,
):
    if not 2 <= len(paths) <= 1000 or len(paths) != len(times):
        raise ValueError(
            "Supply 2–1000 shareable receipts and one explicit time per receipt"
        )
    timestamps = [_time(value) for value in times]
    if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
        raise ValueError("Times must be unique and supplied in chronological order")
    if type(reference) is not int or not 0 <= reference < len(paths):
        raise ValueError("Invalid reference period index")
    if (
        _finite(practical_threshold) is None
        or practical_threshold < 0
        or _finite(prevalence_threshold) is None
        or not 0 <= prevalence_threshold <= 1
    ):
        raise ValueError("Invalid practical/prevalence threshold")
    series = model_identity(series)
    model = model_identity(model)
    critical = []
    for pair in critical_slices:
        if len(pair) != 2:
            raise ValueError("Critical slices require column/value pairs")
        critical.append([_token(pair[0]), _token(pair[1])])
    records, sources, seen, compatibility, artifact_digest = [], [], set(), None, None
    for index, path in enumerate(paths):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != "evaluation-receipt/v1"
            or payload.get("scope") != "shareable"
            or "local" in payload
        ):
            raise ValueError("Trends accept only already-shareable evaluation receipts")
        validate_receipt_shape(payload)
        verified = verify_payload(
            payload,
            signing_secret=signing_secret,
            trust_store=trust_store,
            require_trusted_signer=require_trusted_signer,
        )
        if not verified["valid"]:
            raise ValueError("A trend source failed receipt verification")
        digest = verified["payload_sha256"]
        if digest in seen or payload["receipt_id"] in seen:
            raise ValueError("Duplicated trend source receipt")
        seen.update((digest, payload["receipt_id"]))
        shared = payload["shareable"]
        _mapping(shared.get("privacy"))
        _mapping(shared.get("privacy", {}).get("mechanism", {}))
        _mapping(shared.get("privacy", {}).get("release", {}))
        _mapping(shared.get("benchmark", {}))
        release = shared.get("privacy", {}).get("release", {})
        if (
            release.get("decision") != "allow"
            or release.get("status") != "pass"
            or release.get("publishable") is not True
        ):
            raise ValueError(
                "Every source requires a successful upstream release decision"
            )
        evaluation = _mapping(shared["evaluation"])
        _mapping(evaluation.get("input_schema", {}))
        protocol = protocol_identity(evaluation.get("protocol"))
        chosen = metric or protocol["primary_metric"]
        mode = shared.get("privacy", {}).get("mechanism", {}).get("mode", "none")
        if (
            chosen not in protocol["metrics"]
            or mode not in {"none", "metric_perturbation"}
            or evaluation.get("metric_source") != "reported_metrics"
            or evaluation.get("input_schema", {}).get("schema_version")
            != "prediction-table/v1"
        ):
            raise ValueError("Unsupported trend metric, schema, or metric basis")
        key = {
            "protocol": protocol,
            "metric": chosen,
            "task_type": evaluation.get("task_type"),
            "benchmark": shared.get("benchmark", {}),
            "privacy_mode": mode,
        }
        if compatibility is not None and compatibility != key:
            raise ValueError(
                "Incompatible protocol, benchmark/series basis, task, or metric basis"
            )
        compatibility = key
        from privatelabbench.protocols import TASK_METRICS

        if (
            key["task_type"] not in TASK_METRICS
            or not set(protocol["metrics"]) <= TASK_METRICS[key["task_type"]]
        ):
            raise ValueError("Source protocol metrics conflict with the task type")
        claimed = _mapping(payload.get("signer_statement", {})).get("model")
        if claimed is not None and model_identity(claimed) != model:
            raise ValueError(
                "Model declaration conflicts with the source signer statement"
            )
        context = _mapping(evaluation.get("external_validation", {}))
        if context:
            from privatelabbench.external_validation import model_metadata

            declared = model_metadata(context.get("model", {}))
            if (
                model_identity({field: declared[field] for field in ("id", "revision")})
                != model
            ):
                raise ValueError("Trend model differs from source validation model")
            current_digest = declared.get("artifact_sha256")
            if artifact_digest is not None and artifact_digest != current_digest:
                raise ValueError("Conflicting immutable model artifact digests")
            artifact_digest = current_digest
        quality = None
        if quality_policy is not None:
            from privatelabbench.quality import evaluate_quality_gate

            quality = evaluate_quality_gate(payload, quality_policy)
        row = _record(evaluation, shared, timestamps[index], chosen, mode, quality)
        row["source_receipt_sha256"] = digest
        records.append(row)
        sources.append(
            {
                "receipt_id": payload["receipt_id"],
                "payload_sha256": digest,
                "verification": verified["evidence_level"],
                "model_identity_bound": verified.get("model_identity_bound", False),
            }
        )
    summaries = _summarize(
        records, chosen, reference, practical_threshold, prevalence_threshold, critical
    )
    shared = {
        "series": series,
        "model": model,
        **compatibility,
        "reference_index": reference,
        "practical_threshold": practical_threshold,
        "prevalence_threshold": prevalence_threshold,
        "critical_slices": critical,
        "periods": summaries,
        "statistical_scope": "descriptive_changes_with_marginal_interval_bounds",
        "multiplicity": "exploratory_unadjusted",
        "causal_drift_claim": False,
    }
    artifact = {
        "schema_version": SCHEMA,
        "series_artifact_id": str(uuid4()),
        "scope": "local",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "shareable": shared,
        "local": {
            "sources": sources,
            "quality_policy": quality_policy,
            "limitations": [
                "Model/series identities and collection times are declarations; hashes do not establish honest execution or independence.",
                "Marginal bootstrap intervals are approximate. Difference bounds use the union bound, do not recover joint resampling, and are not a simultaneous confidence band.",
                "Changes and prevalence shifts do not establish their cause. Missing intervals do not imply stable performance.",
            ],
        },
    }
    return attach_integrity_metadata(artifact, signing_secret=signing_secret)


def sanitize_trend(value, policy):
    """Recompute all changes from exact approved identities, times, and partitions."""
    from privatelabbench.privacy.export import _mapping

    shared = _mapping(value)
    series, model = (
        model_identity(shared.get("series", {})),
        model_identity(shared.get("model", {})),
    )
    if series != model_identity(policy.get("public_series", {})) or model not in [
        model_identity(item) for item in policy.get("public_models", [])
    ]:
        raise ValueError(
            "Approve the exact series and model identities before releasing a trend"
        )
    if policy.get("include_protocol") is not True:
        raise ValueError("Trend release requires explicit protocol identity approval")
    protocol = protocol_identity(shared.get("protocol"))
    metric = shared.get("metric")
    if metric not in protocol["metrics"]:
        raise ValueError("Trend metric must be declared by its protocol")
    from privatelabbench.protocols import TASK_METRICS

    if (
        shared.get("task_type") not in TASK_METRICS
        or not set(protocol["metrics"]) <= TASK_METRICS[shared["task_type"]]
    ):
        raise ValueError("Trend task and protocol metrics conflict")
    mode = shared.get("privacy_mode")
    if mode not in {"none", "metric_perturbation"}:
        raise ValueError("Unsupported trend metric basis")
    periods = shared.get("periods")
    approved_times = [_time(value) for value in policy.get("public_times", [])]
    if (
        not isinstance(periods, list)
        or not 2 <= len(periods) <= 1000
        or len(periods) != len(approved_times)
    ):
        raise ValueError("Every period time requires explicit approval")
    if approved_times != sorted(approved_times) or len(set(approved_times)) != len(
        approved_times
    ):
        raise ValueError("Approved times must be unique and chronological")
    reference = shared.get("reference_index")
    threshold, prevalence = (
        _finite(shared.get("practical_threshold")),
        _finite(shared.get("prevalence_threshold")),
    )
    if (
        type(reference) is not int
        or not 0 <= reference < len(periods)
        or threshold is None
        or threshold < 0
        or prevalence is None
        or not 0 <= prevalence <= 1
    ):
        raise ValueError("Invalid trend reference or thresholds")

    def interval(value, point):
        if mode != "none" or value is None:
            return None
        source = _mapping(value)
        lower, upper, level = (
            _finite(source.get(key)) for key in ("lower", "upper", "confidence_level")
        )
        if (
            point is None
            or lower is None
            or upper is None
            or lower > upper
            or level is None
            or not 0 < level < 1
        ):
            raise ValueError("Invalid trend interval")
        return {"lower": lower, "upper": upper, "confidence_level": level}

    records = []
    for index, candidate in enumerate(periods):
        candidate = _mapping(candidate)
        time = _time(candidate.get("time"))
        if time != approved_times[index]:
            raise ValueError("Trend time differs from approved collection time")
        n = candidate.get("n_samples")
        units = candidate.get("n_independent_units")
        if type(n) is not int or n < policy["min_samples"]:
            raise ValueError("Every period must satisfy the sample release floor")
        if units is not None and (
            type(units) is not int
            or not max(policy["min_samples"], policy["min_cell_size"]) <= units <= n
        ):
            raise ValueError(
                "Every period must satisfy the independent-unit release floor"
            )
        point = _finite(candidate.get("estimate"))
        slices = {}
        for column, approved_labels in policy.get("slices", {}).items():
            groups = _mapping(_mapping(candidate.get("slices", {})).get(column, {}))
            if not groups or not set(groups) <= set(approved_labels):
                raise ValueError(
                    "Approve the complete slice partition across every period"
                )
            slices[column] = {}
            total = 0
            for label, group in groups.items():
                group = _mapping(group)
                count = group.get("n_samples")
                if type(count) is not int or count < policy["min_cell_size"]:
                    raise ValueError("Small trend slices cannot be released")
                group_units = group.get("n_independent_units")
                if group_units is not None and (
                    type(group_units) is not int
                    or not policy["min_cell_size"] <= group_units <= count
                ):
                    raise ValueError(
                        "Small independent-unit trend slices cannot be released"
                    )
                total += count
                estimate = _finite(group.get("estimate"))
                slices[column][label] = {
                    "n_samples": count,
                    "n_independent_units": group_units,
                    "estimate": estimate,
                    "interval": interval(group.get("interval"), estimate),
                }
            if total != n:
                raise ValueError("Trend slices must form a complete disjoint partition")
        gate = (
            candidate.get("quality_gate", "not_available")
            if policy.get("include_quality_gate")
            else "not_available"
        )
        if gate not in {"not_available", "pass", "fail", "investigate"}:
            raise ValueError("Invalid trend quality status")
        diagnostic = (
            candidate.get("cohort_diagnostics", "not_in_source_receipt")
            if policy.get("include_degradation")
            else "withheld"
        )
        if diagnostic not in {
            "available_in_source_receipt",
            "not_in_source_receipt",
            "withheld",
        }:
            raise ValueError("Invalid source diagnostic reference")
        row = {
            "time": time,
            "n_samples": n,
            "n_independent_units": units,
            "estimate": point,
            "interval": interval(candidate.get("interval"), point),
            "slices": slices,
            "quality_gate": gate,
            "cohort_diagnostics": diagnostic,
        }
        if policy.get("include_source_receipts"):
            digest = candidate.get("source_receipt_sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("Invalid source receipt digest")
            row["source_receipt_sha256"] = digest
        records.append(row)
    if not any(row["estimate"] is not None for row in records):
        raise ValueError("No defined trend estimates to release")
    critical = []
    for pair in shared.get("critical_slices", []):
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("Invalid critical trend slice")
        if pair[1] in policy.get("slices", {}).get(pair[0], []):
            critical.append(pair)
    benchmark = dict(policy.get("public_benchmark", {}))
    if any(
        shared.get("benchmark", {}).get(key) != item for key, item in benchmark.items()
    ):
        raise ValueError("Approved benchmark identity differs from the source series")
    return {
        "series": series,
        "model": model,
        "protocol": protocol,
        "metric": metric,
        "task_type": shared["task_type"],
        "benchmark": benchmark,
        "privacy_mode": mode,
        "reference_index": reference,
        "practical_threshold": threshold,
        "prevalence_threshold": prevalence,
        "critical_slices": critical,
        "periods": _summarize(
            records, metric, reference, threshold, prevalence, critical
        ),
        "statistical_scope": "descriptive_changes_with_marginal_interval_bounds",
        "multiplicity": "exploratory_unadjusted",
        "causal_drift_claim": False,
    }


def render_trend(artifact):
    shared = artifact["shareable"]
    metric = shared["metric"]
    lines = [
        "# Longitudinal evaluation",
        "",
        f"Series: {shared['series']['id']}@{shared['series']['revision']}",
        f"Model: {shared['model']['id']}@{shared['model']['revision']}",
        f"Metric: {metric}; positive degradation means worse performance.",
        "",
        "| Collection time | N | Estimate | Change from reference | Change from previous | Uncertainty | Quality |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]

    def number(value):
        return f"{value:.6g}" if value is not None else "unavailable"

    for row in shared["periods"]:
        change, previous = row["from_reference"], row["from_previous"]
        lines.append(
            f"| {row['time']} | {row['n_samples']} | {number(row['estimate'])} | {number(change['degradation'])} | {number(previous['degradation']) if previous else 'reference'} | {change['uncertainty_assessment']} | {row['quality_gate']} |"
        )
    lines.extend(
        [
            "",
            "Differences retain their practical threshold and available marginal interval bounds in the JSON artifact. Two 95% marginal intervals yield a 90% union-bound coverage floor for their difference, conditional on marginal coverage; they do not become a 95% paired interval. Bootstrap coverage is approximate. Period and slice scans are exploratory, not a simultaneous confidence band or a causal drift claim.",
        ]
    )
    for row in shared["periods"]:
        changes = [
            item
            for item in row["slice_changes"]
            if item["presence"] != "both"
            or item["material_prevalence_change"]
            or item["from_reference"]
            and item["from_reference"]["point_change"] == "degradation"
        ]
        for item in changes:
            lines.append(
                f"- {row['time']}: {item['column']}={item['value']}; {item['presence']}; prevalence change {item['prevalence_change']:+.1%}; {'critical' if item['critical'] else 'exploratory'}."
            )
    return "\n".join(lines) + "\n"


def trend_command(args):
    from privatelabbench.privacy.export import (
        atomic_write_json,
        publish_shareable_artifact,
    )

    def read(path):
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) if path else None

    import yaml

    output = Path(args.out).resolve()
    public, markdown = (
        output.with_name(output.stem + ".shareable.json"),
        output.with_suffix(".md"),
    )
    protected = {
        Path(path).resolve()
        for path in [
            *args.inputs,
            args.quality_policy,
            args.release_policy,
            args.trust_store,
        ]
        if path
    }
    targets = [
        output,
        public,
        markdown,
        public.with_suffix(".release-audit.json"),
        output.parent / ".plb-release-ledger.json",
        output.parent / ".plb-release.lock",
    ]
    from privatelabbench.core.local_io import validate_output_paths

    try:
        validate_output_paths(protected, targets)
    except (ValueError, OSError) as exc:
        print(f"Trend rejected: {exc}")
        return 2
    public.unlink(missing_ok=True)
    markdown.unlink(missing_ok=True)
    try:

        def identity(value):
            if "@" not in value:
                raise ValueError("Series/model identities require id@revision")
            name, revision = value.rsplit("@", 1)
            return {"id": name, "revision": revision}

        critical = [value.split("=", 1) for value in args.critical_slice]
        artifact = trend_receipts(
            args.inputs,
            times=args.time,
            series=identity(args.series),
            model=identity(args.model),
            metric=args.metric,
            reference=args.reference_index,
            practical_threshold=args.practical_threshold,
            prevalence_threshold=args.prevalence_threshold,
            critical_slices=critical,
            quality_policy=read(args.quality_policy),
            signing_secret=args.signing_secret,
            trust_store=read(args.trust_store),
            require_trusted_signer=args.require_trusted_signer,
        )
        atomic_write_json(output, artifact)
        decision = publish_shareable_artifact(
            artifact,
            read(args.release_policy),
            public,
            signing_secret=args.signing_secret,
        )
        if decision.decision == "allow":
            markdown.write_text(
                render_trend(json.loads(public.read_text(encoding="utf-8"))),
                encoding="utf-8",
            )
        print(f"Local longitudinal series: {output}")
        for row in artifact["shareable"]["periods"]:
            change = row["from_reference"]
            print(
                f"{row['time']}: {row['estimate']}; {change['point_change']}; uncertainty: {change['uncertainty_assessment']}; quality: {row['quality_gate']}"
            )
        print(f"Release: {decision.decision}")
        latest = artifact["shareable"]["periods"][-1]["quality_gate"]
        return 1 if latest == "fail" else 2 if latest == "investigate" else 0
    except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError) as exc:
        public.unlink(missing_ok=True)
        markdown.unlink(missing_ok=True)
        print(f"Trend rejected: {exc}")
        return 2
