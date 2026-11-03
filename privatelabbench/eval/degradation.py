"""Reference/current diagnostics with explicit, independent-cohort uncertainty."""

from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from privatelabbench.eval.metrics import METRIC_DIRECTIONS
from privatelabbench.eval.predictions import evaluate_prediction_table
from privatelabbench.eval.uncertainty import (
    BootstrapConfig,
    _generic_bootstrap_values,
    _interval_entry,
    _regression_bootstrap_values,
)
from privatelabbench.evaluate import prediction_bindings

SUMMARY_SCHEMA = "degradation-summary/v1"
LIMITATIONS = [
    "Performance changes and distribution distances are descriptive, not causal explanations.",
    "The same model, label order, units, and scoring semantics are assumed across cohorts.",
    "Independent-cohort bootstrap assumes independent observations within and between cohorts; repeated or clustered observations need a suitable sampling design.",
    "Slice intervals are exploratory and unadjusted for multiple comparisons.",
    "Changing cohort composition can change aggregate performance even when within-slice performance is stable.",
]


def _finite(value: Any) -> float | None:
    return (
        float(value)
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        else None
    )


def _thresholds(value: Mapping[str, Any]) -> dict[str, float]:
    if not isinstance(value, Mapping) or any(
        key not in METRIC_DIRECTIONS or _finite(item) is None or item < 0
        for key, item in value.items()
    ):
        raise ValueError(
            "practical_thresholds must map supported metrics to finite, nonnegative thresholds"
        )
    return dict(value)


def _encoded(frame, target, predictions, task_type, labels):
    if task_type == "regression":
        y = frame[target].to_numpy(dtype=float)
    else:
        mapping = {str(label): index for index, label in enumerate(labels)}
        y = frame[target].astype(str).map(mapping).to_numpy(dtype=int)
    p = frame[predictions].to_numpy(dtype=float)
    return y, p[:, 0] if len(predictions) == 1 else p


def _samples(y, p, *, task_type, names, config, rng, plan=None):
    if plan is not None:
        from privatelabbench.eval.sampling import bootstrap_samples

        return bootstrap_samples(
            y,
            p,
            task_type=task_type,
            metric_names=tuple(names),
            plan=plan,
            resamples=config.resamples,
            rng=rng,
        )
    if task_type == "regression":
        return _regression_bootstrap_values(y, p, resamples=config.resamples, rng=rng)
    return _generic_bootstrap_values(
        y,
        p,
        task_type=task_type,
        metric_names=tuple(names),
        resamples=config.resamples,
        rng=rng,
    )


def _changes(
    reference,
    current,
    y_ref,
    p_ref,
    y_cur,
    p_cur,
    *,
    task_type,
    config,
    independent,
    overlapping,
    thresholds,
    sampling_design=None,
    metadata_reference=None,
    metadata_current=None,
):
    from privatelabbench.eval.sampling import plan_sampling, ResampleLimit

    plan_a = (
        plan_sampling(metadata_reference, sampling_design) if sampling_design else None
    )
    plan_b = (
        plan_sampling(metadata_current, sampling_design) if sampling_design else None
    )
    units = (
        {
            "n_independent_units_reference": plan_a.n_units,
            "n_independent_units_current": plan_b.n_units,
        }
        if plan_a
        else {}
    )
    overlapping = overlapping or bool(plan_a and plan_a.root_ids & plan_b.root_ids)
    if not config.enabled:
        status = "disabled"
    elif not independent:
        status = "independence_not_declared"
    elif overlapping:
        status = "overlapping_cohorts_not_supported"
    elif plan_a and (plan_a.status != "evaluated" or plan_b.status != "evaluated"):
        status = plan_a.status if plan_a.status != "evaluated" else plan_b.status
    elif min(len(y_ref), len(y_cur)) < config.min_samples:
        status = "skipped_min_samples"
    else:
        status = "evaluated"
    ref_values = cur_values = None
    if status == "evaluated":
        ref_seed, cur_seed = np.random.SeedSequence(config.seed).spawn(2)
        try:
            ref_values = _samples(
                y_ref,
                p_ref,
                task_type=task_type,
                names=reference,
                config=config,
                rng=np.random.default_rng(ref_seed),
                plan=plan_a,
            )
            cur_values = _samples(
                y_cur,
                p_cur,
                task_type=task_type,
                names=current,
                config=config,
                rng=np.random.default_rng(cur_seed),
                plan=plan_b,
            )
        except ResampleLimit:
            status = "not_supported_resource_limit"
    changes = {}
    for name in sorted(set(reference) | set(current)):
        a, b = _finite(reference.get(name)), _finite(current.get(name))
        sign = 1 if METRIC_DIRECTIONS[name] == "lower_is_better" else -1
        delta = b - a if a is not None and b is not None else None
        degradation = sign * delta if delta is not None else None
        threshold = thresholds.get(name, 0.0)
        decision = (
            "undefined"
            if degradation is None
            else (
                "degraded"
                if degradation > threshold
                else "improved" if degradation < -threshold else "within_threshold"
            )
        )
        interval = {"status": status, "lower": None, "upper": None}
        if status == "evaluated":
            interval = _interval_entry(
                estimate=degradation if degradation is not None else float("nan"),
                values=sign * (cur_values[name] - ref_values[name]),
                confidence_level=config.confidence_level,
                requested_resamples=config.resamples,
            )
        interval.update(units)
        changes[name] = {
            "reference": a,
            "current": b,
            "raw_delta_current_minus_reference": delta,
            "degradation": degradation,
            "relative_degradation": (
                degradation / abs(a) if degradation is not None and a else None
            ),
            "practical_threshold": threshold,
            "status": decision,
            "interval": interval,
        }
    return changes


def _numeric_distribution(a, b):
    a = pd.to_numeric(a, errors="raise").to_numpy(dtype=float)
    b = pd.to_numeric(b, errors="raise").to_numpy(dtype=float)
    if np.isinf(a).any() or np.isinf(b).any():
        raise ValueError(
            "Numeric distribution metadata must contain finite values or explicit missing values"
        )
    finite_a, finite_b = a[np.isfinite(a)], b[np.isfinite(b)]
    counts = {
        "n_reference": len(a),
        "n_current": len(b),
        "missing_reference": len(a) - len(finite_a),
        "missing_current": len(b) - len(finite_b),
    }
    if not len(finite_a) or not len(finite_b):
        return {"type": "numeric", "status": "not_testable", **counts}
    points = np.sort(np.concatenate((finite_a, finite_b)))
    distance = float(
        np.max(
            np.abs(
                np.searchsorted(np.sort(finite_a), points, side="right") / len(finite_a)
                - np.searchsorted(np.sort(finite_b), points, side="right")
                / len(finite_b)
            )
        )
    )
    mean_a, mean_b = float(np.mean(finite_a)), float(np.mean(finite_b))
    std_a = float(np.std(finite_a))
    return {
        "type": "numeric",
        "status": "evaluated",
        **counts,
        "mean_reference": mean_a,
        "mean_current": mean_b,
        "std_reference": std_a,
        "std_current": float(np.std(finite_b)),
        "standardized_mean_change": (mean_b - mean_a) / std_a if std_a else None,
        "ks_distance": distance,
    }


def _categorical_distribution(a, b):
    # Missingness remains a separate count; no reserved sentinel can collide with a real label.
    counts_a, counts_b = (
        a.dropna().astype(str).value_counts(),
        b.dropna().astype(str).value_counts(),
    )
    levels = sorted(set(counts_a.index) | set(counts_b.index))
    n_a, n_b = int(counts_a.sum()), int(counts_b.sum())
    counts = {
        "n_reference": len(a),
        "n_current": len(b),
        "missing_reference": len(a) - n_a,
        "missing_current": len(b) - n_b,
    }
    if not n_a or not n_b:
        return {"type": "categorical", "status": "not_testable", **counts}
    distance = 0.5 * sum(
        abs(counts_a.get(level, 0) / n_a - counts_b.get(level, 0) / n_b)
        for level in levels
    )
    return {
        "type": "categorical",
        "status": "evaluated",
        **counts,
        "min_observed_cell": int(min(counts_a.min(), counts_b.min())),
        "total_variation_distance": float(distance),
    }


def diagnose_shift(
    reference_path: str,
    current_path: str,
    *,
    target: str,
    prediction_column: str | None = None,
    prediction_columns: Sequence[str] | None = None,
    task_type: str | None = None,
    class_labels: Sequence[str] | None = None,
    sample_id_column: str = "sample_id",
    slice_columns: Sequence[str] = (),
    min_slice_size: int = 5,
    metric: str | None = None,
    uncertainty_config: BootstrapConfig | None = None,
    independent_cohorts: bool = False,
    practical_thresholds: Mapping[str, Any] | None = None,
    prevalence_threshold: float = 0.1,
    numeric_metadata: Sequence[str] = (),
    categorical_metadata: Sequence[str] = (),
    sampling_design: Any = None,
    current_frame: pd.DataFrame | None = None,
    reference_frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    if (
        type(independent_cohorts) is not bool
        or _finite(prevalence_threshold) is None
        or not 0 <= prevalence_threshold <= 1
    ):
        raise ValueError(
            "Declare boolean independent_cohorts and prevalence_threshold between zero and one"
        )
    thresholds = _thresholds(practical_thresholds or {})
    config = uncertainty_config or BootstrapConfig(enabled=True)
    config.validate()
    from privatelabbench.eval.sampling import (
        sampling_design as parse_design,
        plan_sampling,
    )

    design = parse_design(sampling_design)
    slice_columns = (
        tuple(
            dict.fromkeys(
                [*slice_columns, *[column for column, value in design.critical_slices]]
            )
        )
        if design
        else slice_columns
    )
    dtypes = {
        sample_id_column: "string",
        **({column: "string" for column in design.metadata_columns} if design else {}),
    }
    frames = [reference_frame if reference_frame is not None else pd.read_csv(reference_path, dtype=dtypes), current_frame if current_frame is not None else pd.read_csv(current_path, dtype=dtypes)]
    bindings = prediction_bindings(
        reference_path,
        frame=frames[0],
        target=target,
        prediction_column=prediction_column,
        prediction_columns=prediction_columns,
        task_type=task_type,
        class_labels=class_labels,
        sample_id_column=sample_id_column,
        slices=slice_columns,
        metadata=[*numeric_metadata, *categorical_metadata],
    )
    task_type, labels = bindings["task_type"], bindings["class_labels"]
    prediction_column = bindings.get("prediction_column")
    prediction_columns = bindings.get("prediction_columns")
    prediction_bindings(
        current_path,
        frame=frames[1],
        target=target,
        prediction_column=prediction_column,
        prediction_columns=prediction_columns,
        task_type=task_type,
        class_labels=labels,
        sample_id_column=sample_id_column,
        slices=slice_columns,
        metadata=[*numeric_metadata, *categorical_metadata],
    )
    predictions = (
        list(prediction_columns) if prediction_columns else [prediction_column]
    )
    evaluations = [
        evaluate_prediction_table(
            frame,
            dataset_path=path,
            target=target,
            prediction_column=prediction_column,
            prediction_columns=prediction_columns,
            task_type=task_type,
            class_labels=labels,
            sample_id_column=sample_id_column,
            require_sample_id=True,
            slice_columns=slice_columns,
            min_slice_size=min_slice_size,
            sampling_design=design,
        )
        for frame, path in zip(frames, (reference_path, current_path))
    ]
    ref, cur = evaluations
    metric = (
        metric
        or {
            "regression": "rmse",
            "classification": "auroc",
            "multiclass": "macro_auroc_ovr",
        }[task_type]
    )
    if metric not in ref.metrics or not set(thresholds) <= set(ref.metrics):
        raise ValueError("Diagnostic metric/thresholds must be supported by the task")
    y_ref, p_ref = _encoded(frames[0], target, predictions, task_type, labels)
    y_cur, p_cur = _encoded(frames[1], target, predictions, task_type, labels)
    overlapping = bool(
        set(frames[0][sample_id_column].astype(str))
        & set(frames[1][sample_id_column].astype(str))
    )
    overall = _changes(
        ref.metrics,
        cur.metrics,
        y_ref,
        p_ref,
        y_cur,
        p_cur,
        task_type=task_type,
        config=config,
        independent=independent_cohorts,
        overlapping=overlapping,
        thresholds=thresholds,
        sampling_design=design,
        metadata_reference=frames[0],
        metadata_current=frames[1],
    )
    slices, ranking = {}, []
    seed_offset = 0
    for column in slice_columns:
        groups_a, groups_b = ref.slice_metrics[column], cur.slice_metrics[column]
        slices[column] = {}
        normalized_a, normalized_b = (
            frame[column].map(lambda value: "<NA>" if pd.isna(value) else str(value))
            for frame in frames
        )
        for label in sorted(set(groups_a) | set(groups_b)):
            a, b = groups_a.get(label, {}), groups_b.get(label, {})
            n_a, n_b = a.get("n", 0), b.get("n", 0)
            prevalence_delta = n_b / cur.n_samples - n_a / ref.n_samples
            status = (
                "new_slice"
                if not n_a
                else (
                    "missing_slice"
                    if not n_b
                    else (
                        "skipped_min_slice_size"
                        if min(n_a, n_b) < min_slice_size
                        else "evaluated"
                    )
                )
            )
            entry = {
                "n_reference": n_a,
                "n_current": n_b,
                "prevalence_reference": n_a / ref.n_samples,
                "prevalence_current": n_b / cur.n_samples,
                "prevalence_change": prevalence_delta,
                "material_prevalence_change": abs(prevalence_delta)
                > prevalence_threshold,
                "status": status,
                "metrics": {},
            }
            i_a, i_b = np.flatnonzero(normalized_a == label), np.flatnonzero(
                normalized_b == label
            )
            if design:
                entry["n_independent_units_reference"] = plan_sampling(
                    frames[0].iloc[i_a], design
                ).n_units
                entry["n_independent_units_current"] = plan_sampling(
                    frames[1].iloc[i_b], design
                ).n_units
            if status == "evaluated":
                seed_offset += 1
                i_a, i_b = np.flatnonzero(normalized_a == label), np.flatnonzero(
                    normalized_b == label
                )
                entry["metrics"] = _changes(
                    a["metrics"],
                    b["metrics"],
                    y_ref[i_a],
                    p_ref[i_a],
                    y_cur[i_b],
                    p_cur[i_b],
                    task_type=task_type,
                    config=replace(
                        config,
                        enabled=config.enabled and config.include_slices,
                        seed=config.seed + seed_offset,
                    ),
                    independent=independent_cohorts,
                    overlapping=overlapping,
                    thresholds=thresholds,
                    sampling_design=design,
                    metadata_reference=frames[0].iloc[i_a].reset_index(drop=True),
                    metadata_current=frames[1].iloc[i_b].reset_index(drop=True),
                )
                delta = entry["metrics"][metric]["degradation"]
                if delta is not None:
                    ranking.append(
                        {
                            "column": column,
                            "value": label,
                            "degradation": delta,
                            "status": entry["metrics"][metric]["status"],
                        }
                    )
            slices[column][label] = entry
    distributions = {
        "target": (
            _numeric_distribution
            if task_type == "regression"
            else _categorical_distribution
        )(frames[0][target], frames[1][target])
    }
    for index, column in enumerate(predictions):
        distributions[
            "prediction" if len(predictions) == 1 else f"prediction-{index+1}"
        ] = _numeric_distribution(frames[0][column], frames[1][column])
    if len(set(numeric_metadata) | set(categorical_metadata)) != len(
        numeric_metadata
    ) + len(categorical_metadata):
        raise ValueError("Numeric and categorical metadata selections must be distinct")
    for columns, function in (
        (numeric_metadata, _numeric_distribution),
        (categorical_metadata, _categorical_distribution),
    ):
        for column in columns:
            if column in distributions:
                raise ValueError(
                    "Metadata feature names cannot collide with target/prediction diagnostic aliases"
                )
            distributions[column] = function(frames[0][column], frames[1][column])
    summary = {
        "schema_version": SUMMARY_SCHEMA,
        "metric_basis": "clean_metrics",
        "metric": metric,
        "n_reference": ref.n_samples,
        "n_current": cur.n_samples,
        "overall": overall,
        "slices": slices,
        "ranked_slices": sorted(
            ranking, key=lambda entry: entry["degradation"], reverse=True
        ),
        "distributions": distributions,
        "prevalence_threshold": prevalence_threshold,
        "uncertainty": {
            **config.as_dict(),
            "schema_version": "cohort-delta-uncertainty/v1",
            "method": (
                "independent_percentile_bootstrap"
                if not design
                else (
                    "independent_cluster_percentile_bootstrap"
                    if design.method == "cluster_bootstrap"
                    else "independent_hierarchical_percentile_bootstrap"
                )
            ),
            "independent_cohorts_declared": independent_cohorts,
            "overlapping_sample_ids": overlapping,
            **(
                {
                    "sampling_design": design.as_dict(),
                    "overlapping_independent_units": bool(
                        plan_sampling(frames[0], design).root_ids
                        & plan_sampling(frames[1], design).root_ids
                    ),
                }
                if design
                else {}
            ),
            "sampling": (
                "independent_clusters"
                if design and design.method == "cluster_bootstrap"
                else (
                    "nested_clusters"
                    if design
                    else (
                        "iid_rows"
                        if task_type == "regression"
                        else "stratified_by_target"
                    )
                )
            ),
        },
        "limitations": LIMITATIONS,
    }
    return {
        "degradation_summary": summary,
        "local": {
            "reference_path": str(Path(reference_path).resolve()),
            "current_path": str(Path(current_path).resolve()),
            "class_labels": labels,
        },
    }


def sanitize_degradation(
    value: Mapping[str, Any], policy: Mapping[str, Any]
) -> dict[str, Any]:
    """Approve both cohort sizes and complete slice partitions before publication."""
    from privatelabbench.privacy.export import _mapping, _number, _statistics
    from privatelabbench.aggregate import _count

    summary = _mapping(value)
    if (
        summary.get("schema_version") != SUMMARY_SCHEMA
        or summary.get("metric_basis") != "clean_metrics"
    ):
        raise ValueError("Unsupported degradation summary schema")
    n_a, n_b = _count(summary.get("n_reference")), _count(summary.get("n_current"))
    if min(n_a, n_b) < policy["min_samples"]:
        raise ValueError(
            "Both reference and current cohorts must satisfy the release minimum"
        )
    primary = summary.get("metric")
    if policy.get("require_privacy_audit", True):
        raise ValueError(
            "Separate reference-cohort privacy evidence is unavailable; required audits cannot be satisfied by the current cohort alone"
        )
    if primary not in METRIC_DIRECTIONS:
        raise ValueError("Unsupported degradation metric")
    uncertainty_metadata = _mapping(summary.get("uncertainty"))
    declaration = uncertainty_metadata.get("independent_cohorts_declared")
    overlap = uncertainty_metadata.get(
        "overlapping_sample_ids", False
    ) or uncertainty_metadata.get("overlapping_independent_units", False)
    if (
        type(declaration) is not bool
        or type(overlap) is not bool
        or uncertainty_metadata.get("method")
        not in {
            "independent_percentile_bootstrap",
            "independent_cluster_percentile_bootstrap",
            "independent_hierarchical_percentile_bootstrap",
        }
        or uncertainty_metadata.get("schema_version") != "cohort-delta-uncertainty/v1"
    ):
        raise ValueError("Invalid cohort uncertainty method/declaration")
    for key in ("seed", "resamples", "min_samples"):
        if (
            type(uncertainty_metadata.get(key)) is not int
            or uncertainty_metadata[key] < 0
        ):
            raise ValueError("Invalid cohort resampling configuration")
    if (
        type(uncertainty_metadata.get("enabled")) is not bool
        or type(uncertainty_metadata.get("include_slices")) is not bool
    ):
        raise ValueError("Invalid cohort resampling flags")
    BootstrapConfig(
        enabled=uncertainty_metadata["enabled"],
        confidence_level=uncertainty_metadata["confidence_level"],
        resamples=uncertainty_metadata["resamples"],
        min_samples=uncertainty_metadata["min_samples"],
        seed=uncertainty_metadata["seed"],
    ).validate()

    def change(entry, name, *, full_cohort=False):
        entry = _mapping(entry)
        a, b = _number(entry.get("reference")), _number(entry.get("current"))
        threshold = _number(entry.get("practical_threshold", 0.0))
        if threshold is None or threshold < 0:
            raise ValueError("Invalid degradation threshold")
        delta = b - a if a is not None and b is not None else None
        degradation = (
            delta * (1 if METRIC_DIRECTIONS[name] == "lower_is_better" else -1)
            if delta is not None
            else None
        )
        interval = _mapping(entry.get("interval", {}))
        status = interval.get("status", "disabled")
        if status not in {
            "evaluated",
            "disabled",
            "independence_not_declared",
            "overlapping_cohorts_not_supported",
            "skipped_min_samples",
            "undefined_point_estimate",
            "insufficient_valid_resamples",
            "skipped_min_independent_units",
            "skipped_min_units_per_stratum",
            "not_supported_missing_cluster_columns",
            "not_supported_missing_cluster_ids",
            "not_supported_nonconstant_cluster_strata",
            "not_supported_crossed_clusters",
            "not_supported_resource_limit",
            "withheld_small_independent_unit_count",
        }:
            raise ValueError("Invalid degradation interval status")
        low, high = _number(interval.get("lower")), _number(interval.get("upper"))
        unit_counts = {
            key: interval[key]
            for key in ("n_independent_units_reference", "n_independent_units_current")
            if key in interval
        }
        if unit_counts and (
            len(unit_counts) != 2
            or any(
                type(count) is not int or count < 0 for count in unit_counts.values()
            )
        ):
            raise ValueError("Invalid cohort independent-unit counts")
        if (
            full_cohort
            and unit_counts
            and min(unit_counts.values())
            < max(policy["min_samples"], policy["min_cell_size"])
        ):
            raise ValueError(
                "Both cohort independent-unit counts must meet release minimums"
            )
        if unit_counts and min(unit_counts.values()) < policy["min_cell_size"]:
            status, low, high, unit_counts = (
                "withheld_small_independent_unit_count",
                None,
                None,
                {},
            )
        if status == "evaluated" and (
            low is None
            or high is None
            or low > high
            or degradation is None
            or not declaration
            or overlap
        ):
            raise ValueError("Invalid degradation confidence interval")
        return {
            "reference": a,
            "current": b,
            "raw_delta_current_minus_reference": delta,
            "degradation": degradation,
            "relative_degradation": (
                degradation / abs(a) if degradation is not None and a else None
            ),
            "practical_threshold": threshold,
            "status": (
                "undefined"
                if degradation is None
                else (
                    "degraded"
                    if degradation > threshold
                    else "improved" if degradation < -threshold else "within_threshold"
                )
            ),
            "interval": {
                "status": status,
                "lower": low if status == "evaluated" else None,
                "upper": high if status == "evaluated" else None,
                **unit_counts,
            },
        }

    def metrics(entries, *, full_cohort=False):
        return {
            name: change(entry, name, full_cohort=full_cohort)
            for name, entry in _mapping(entries).items()
            if name in METRIC_DIRECTIONS
        }

    overall = metrics(summary.get("overall", {}), full_cohort=True)
    if primary not in overall:
        raise ValueError("Primary degradation metric is missing")
    prevalence = _number(summary.get("prevalence_threshold"))
    if prevalence is None or not 0 <= prevalence <= 1:
        raise ValueError("Invalid prevalence threshold")
    slices, ranking = {}, []
    for column, approved in policy.get("slices", {}).items():
        groups = _mapping(_mapping(summary.get("slices", {})).get(column, {}))
        if set(groups) != set(approved) or not groups:
            continue
        counts = [
            (entry.get("n_reference"), entry.get("n_current"))
            for entry in groups.values()
        ]
        if any(
            any(
                key in entry
                and (
                    type(entry[key]) is not int or entry[key] < policy["min_cell_size"]
                )
                for key in (
                    "n_independent_units_reference",
                    "n_independent_units_current",
                )
            )
            for entry in groups.values()
        ):
            continue
        if (
            any(
                type(a) is not int
                or type(b) is not int
                or min(a, b) < policy["min_cell_size"]
                for a, b in counts
            )
            or sum(a for a, b in counts) != n_a
            or sum(b for a, b in counts) != n_b
        ):
            continue
        slices[column] = {}
        for label, entry in groups.items():
            a, b = entry["n_reference"], entry["n_current"]
            delta = b / n_b - a / n_a
            values = metrics(entry.get("metrics", {}))
            slices[column][label] = {
                "n_reference": a,
                "n_current": b,
                "prevalence_reference": a / n_a,
                "prevalence_current": b / n_b,
                "prevalence_change": delta,
                "material_prevalence_change": abs(delta) > prevalence,
                "status": "evaluated" if values else "skipped_min_slice_size",
                "metrics": values,
                **{
                    key: entry[key]
                    for key in (
                        "n_independent_units_reference",
                        "n_independent_units_current",
                    )
                    if key in entry
                },
            }
            if primary in values and values[primary]["degradation"] is not None:
                ranking.append(
                    {
                        "column": column,
                        "value": label,
                        "degradation": values[primary]["degradation"],
                        "status": values[primary]["status"],
                    }
                )
    distributions = {}
    for feature in policy.get("public_shift_features", []):
        entry = _mapping(_mapping(summary.get("distributions", {})).get(feature, {}))
        if (
            not entry
            or entry.get("n_reference") != n_a
            or entry.get("n_current") != n_b
        ):
            continue
        missing = (entry.get("missing_reference"), entry.get("missing_current"))
        if (
            any(type(n) is not int or n < 0 for n in missing)
            or any(0 < n < policy["min_cell_size"] for n in missing)
            or min(n_a - missing[0], n_b - missing[1]) < policy["min_samples"]
        ):
            continue
        if entry.get("status") != "evaluated":
            continue
        numeric = {
            "mean_reference",
            "mean_current",
            "std_reference",
            "std_current",
            "standardized_mean_change",
            "ks_distance",
        }
        categorical = {"total_variation_distance"}
        kind = entry.get("type")
        if kind not in {"numeric", "categorical"}:
            raise ValueError("Invalid distribution diagnostic type")
        if kind == "categorical" and (
            type(entry.get("min_observed_cell")) is not int
            or entry["min_observed_cell"] < policy["min_cell_size"]
        ):
            continue
        distributions[feature] = {
            "type": kind,
            "status": "evaluated",
            "n_reference": n_a,
            "n_current": n_b,
            "missing_reference": missing[0],
            "missing_current": missing[1],
            **{
                key: _number(entry.get(key))
                for key in (numeric if kind == "numeric" else categorical)
            },
        }
    uncertainty = _statistics(
        dict(uncertainty_metadata) | {"method": "percentile_bootstrap"}
    )
    uncertainty["method"] = uncertainty_metadata["method"]
    uncertainty["schema_version"] = "cohort-delta-uncertainty/v1"
    uncertainty["independent_cohorts_declared"] = declaration
    return {
        "schema_version": SUMMARY_SCHEMA,
        "metric_basis": "clean_metrics",
        "metric": primary,
        "n_reference": n_a,
        "n_current": n_b,
        "overall": overall,
        "slices": slices,
        "ranked_slices": sorted(
            ranking, key=lambda row: row["degradation"], reverse=True
        ),
        "distributions": distributions,
        "prevalence_threshold": prevalence,
        "uncertainty": uncertainty,
        "limitations": LIMITATIONS,
    }


def render_degradation(summary: Mapping[str, Any]) -> str:
    lines = [
        "## Reference/current diagnostics",
        "",
        f"Reference N: {summary['n_reference']}; current N: {summary['n_current']}.",
        f"Configured delta intervals: {summary['uncertainty']['confidence_level']:.0%} independent percentile bootstrap; unavailable intervals carry an explicit status.",
        "",
        "Positive degradation means worse current performance. Slice intervals are exploratory and unadjusted.",
        "",
        "| Metric | Reference | Current | Degradation | Relative | Delta interval | Status |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for name, entry in summary["overall"].items():
        text = lambda value: f"{value:.6g}" if value is not None else "undefined"
        interval = entry["interval"]
        interval_text = (
            f"[{interval['lower']:.6g}, {interval['upper']:.6g}]"
            if interval["status"] == "evaluated"
            else interval["status"]
        )
        lines.append(
            f"| {name} | {text(entry['reference'])} | {text(entry['current'])} | {text(entry['degradation'])} | {text(entry['relative_degradation'])} | {interval_text} | {entry['status']} |"
        )
    if summary["ranked_slices"]:
        lines += ["", "Largest slice changes (primary metric):", ""]
        lines += [
            f"- {row['column']}={row['value']}: {row['degradation']:+.6g} ({row['status']})."
            for row in summary["ranked_slices"][:10]
        ]
    lines += ["", *[f"- {item}" for item in LIMITATIONS], ""]
    return "\n".join(lines)
