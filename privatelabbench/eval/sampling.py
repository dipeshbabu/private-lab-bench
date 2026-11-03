"""Declared sampling units and bounded cluster/hierarchical resampling."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Mapping

import numpy as np
import pandas as pd

SCHEMA = "sampling-design/v1"
MULTIPLICITY_SCHEMA = "multiplicity/v1"
ASSUMPTIONS = [
    "Top-level units are independent and exchangeable within declared strata.",
    "Metrics retain observation weighting; sampling clusters does not change the point estimand to a mean of cluster metrics.",
    "Hierarchical resampling assumes exchangeable child units within each sampled parent.",
    "The minimum-unit threshold is an operational safeguard, not a universal coverage guarantee.",
]


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return dict(value)


@dataclass(frozen=True)
class MultiplicityPolicy:
    method: str = "benjamini_yekutieli"
    family: str = "exploratory_slices"
    alpha: float = 0.05
    dependence: str = "arbitrary"

    @classmethod
    def from_dict(cls, value: Any) -> MultiplicityPolicy:
        data = _mapping(value, "multiplicity policy")
        if data.pop("schema_version", None) != MULTIPLICITY_SCHEMA or set(data) - {
            "method",
            "family",
            "alpha",
            "dependence",
        }:
            raise ValueError("Expected multiplicity/v1 and supported policy fields")
        policy = cls(**data)
        if any(
            not isinstance(value, str)
            for value in (policy.method, policy.family, policy.dependence)
        ):
            raise ValueError(
                "Multiplicity method, family, and dependence must be explicit strings"
            )
        if policy.method not in {
            "benjamini_hochberg",
            "benjamini_yekutieli",
        } or policy.family not in {"exploratory_slices", "critical_slices"}:
            raise ValueError("Unsupported multiplicity method/family")
        if (
            isinstance(policy.alpha, bool)
            or not isinstance(policy.alpha, (int, float))
            or not 0 < policy.alpha < 1
        ):
            raise ValueError("Multiplicity alpha must be between zero and one")
        if (
            policy.dependence not in {"arbitrary", "independent_or_prds"}
            or policy.method == "benjamini_hochberg"
            and policy.dependence != "independent_or_prds"
        ):
            raise ValueError(
                "Benjamini-Hochberg requires an explicit independent_or_prds dependence declaration; use Benjamini-Yekutieli for arbitrary dependence"
            )
        return policy

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MULTIPLICITY_SCHEMA,
            "method": self.method,
            "family": self.family,
            "alpha": self.alpha,
            "dependence": self.dependence,
        }


@dataclass(frozen=True)
class SamplingDesign:
    unit: str
    method: str
    cluster_columns: tuple[str, ...]
    sampling_level: str
    strata_column: str | None = None
    resample_rows_within_leaf: bool = False
    min_independent_units: int = 20
    exchangeability: str = "none"
    max_resample_rows: int = 2_000_000
    critical_slices: tuple[tuple[str, str], ...] = ()
    multiplicity: MultiplicityPolicy | None = None

    @classmethod
    def from_dict(cls, value: Any) -> SamplingDesign:
        data = _mapping(value, "sampling design")
        allowed = {
            "schema_version",
            "unit",
            "method",
            "cluster_columns",
            "sampling_level",
            "strata_column",
            "resample_rows_within_leaf",
            "min_independent_units",
            "exchangeability",
            "max_resample_rows",
            "critical_slices",
            "multiplicity",
        }
        if set(data) - allowed or data.pop("schema_version", None) != SCHEMA:
            raise ValueError("Expected sampling-design/v1 and supported design fields")
        columns = data.pop("cluster_columns", None)
        if (
            not isinstance(columns, list)
            or not columns
            or len(columns) > 8
            or any(
                not isinstance(column, str) or not column.strip() for column in columns
            )
            or len(set(columns)) != len(columns)
        ):
            raise ValueError(
                "cluster_columns must be an ordered, unique, nonempty list"
            )
        unit = data.get("unit")
        if not isinstance(unit, str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_-]{0,63}", unit
        ):
            raise ValueError(
                "Declare a short independent-unit name, such as patient, compound, or laboratory"
            )
        method = data.get("method")
        if (
            not isinstance(method, str)
            or method not in {"cluster_bootstrap", "hierarchical_bootstrap"}
            or (method == "cluster_bootstrap" and len(columns) != 1)
            or (method == "hierarchical_bootstrap" and len(columns) < 2)
        ):
            raise ValueError(
                "Cluster bootstrap needs one column; hierarchical bootstrap needs ordered top-to-leaf columns"
            )
        data.setdefault("sampling_level", columns[0])
        if data["sampling_level"] != columns[0]:
            raise ValueError(
                "Only sampling from the declared top independent level is supported"
            )
        for key, default, minimum in (
            ("min_independent_units", 20, 2),
            ("max_resample_rows", 2_000_000, 2),
        ):
            value = data.setdefault(key, default)
            if type(value) is not int or value < minimum:
                raise ValueError(f"{key} must be an integer of at least {minimum}")
        rows = data.setdefault("resample_rows_within_leaf", False)
        if type(rows) is not bool or method == "cluster_bootstrap" and rows:
            raise ValueError(
                "Whole-cluster bootstrap must retain member rows; leaf-row resampling is an explicit hierarchical option"
            )
        strata = data.get("strata_column")
        if strata is not None and (not isinstance(strata, str) or not strata.strip()):
            raise ValueError("strata_column must be a column name or null")
        if not isinstance(data.get("exchangeability", "none"), str) or data.get(
            "exchangeability", "none"
        ) not in {
            "none",
            "model_vectors_within_clusters",
        }:
            raise ValueError(
                "Unsupported prediction-vector exchangeability declaration"
            )
        critical = data.pop("critical_slices", [])
        if not isinstance(critical, list):
            raise ValueError("critical_slices must be a list of column/value selectors")
        selectors = []
        for item in critical:
            if (
                not isinstance(item, Mapping)
                or set(item) != {"column", "value"}
                or any(not isinstance(item[key], str) or not item[key] for key in item)
            ):
                raise ValueError(
                    "Critical slices require explicit string column and value fields"
                )
            selectors.append((item["column"], item["value"]))
        if len(set(selectors)) != len(selectors):
            raise ValueError("Critical slice selectors cannot repeat")
        multiplicity = data.pop("multiplicity", None)
        policy = (
            MultiplicityPolicy.from_dict(multiplicity)
            if multiplicity is not None
            else None
        )
        if policy and policy.family == "critical_slices" and not selectors:
            raise ValueError(
                "A critical-slice test family requires predeclared selectors"
            )
        return cls(
            **data,
            cluster_columns=tuple(columns),
            critical_slices=tuple(selectors),
            multiplicity=policy,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA,
            "unit": self.unit,
            "method": self.method,
            "cluster_columns": list(self.cluster_columns),
            "sampling_level": self.sampling_level,
            "strata_column": self.strata_column,
            "resample_rows_within_leaf": self.resample_rows_within_leaf,
            "min_independent_units": self.min_independent_units,
            "exchangeability": self.exchangeability,
            "max_resample_rows": self.max_resample_rows,
            "critical_slices": [
                {"column": column, "value": value}
                for column, value in self.critical_slices
            ],
            "multiplicity": self.multiplicity.as_dict() if self.multiplicity else None,
        }

    @property
    def metadata_columns(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                [
                    *self.cluster_columns,
                    *([self.strata_column] if self.strata_column else []),
                ]
            )
        )


def sampling_design(value: Any) -> SamplingDesign | None:
    if value is None:
        return None
    return SamplingDesign.from_dict(
        value.as_dict() if isinstance(value, SamplingDesign) else value
    )


@dataclass(frozen=True)
class _Node:
    children: tuple[_Node, ...]
    rows: np.ndarray | None
    n_rows: int


class ResampleLimit(ValueError):
    pass


@dataclass(frozen=True)
class SamplingPlan:
    design: SamplingDesign
    roots: tuple[_Node, ...]
    strata: tuple[tuple[int, ...], ...]
    row_to_root: np.ndarray
    root_ids: frozenset[str]
    status: str
    n_samples: int

    @property
    def n_units(self) -> int:
        return len(self.roots)

    def metadata(self) -> dict[str, Any]:
        sizes = [node.n_rows for node in self.roots]
        flags = ["few_independent_units"] if 0 < self.n_units < 20 else []

        def singleton(node):
            return len(node.children) == 1 or any(
                singleton(child) for child in node.children
            )

        if any(singleton(node) for node in self.roots):
            flags.append("singleton_nested_parent")
        return {
            "sampling_design": self.design.as_dict(),
            "n_independent_units": self.n_units,
            "n_samples": self.n_samples,
            "sampling": (
                "independent_clusters"
                if self.design.method == "cluster_bootstrap"
                else "nested_clusters"
            ),
            "cluster_sizes": (
                {
                    "min": min(sizes),
                    "max": max(sizes),
                    "median": float(np.median(sizes)),
                }
                if sizes
                else {}
            ),
            "estimand": "observation_weighted_metric",
            "assumptions": ASSUMPTIONS,
            "design_status": self.status,
            "reliability_flags": flags,
        }

    def draw(self, rng: np.random.Generator) -> np.ndarray:
        selected, size = [], 0

        def visit(node):
            nonlocal size
            if node.children:
                for index in rng.integers(
                    0, len(node.children), size=len(node.children)
                ):
                    visit(node.children[int(index)])
            else:
                size += len(node.rows)
                if size > self.design.max_resample_rows:
                    raise ResampleLimit(
                        "Resample row budget exceeded; no tail draws may be silently discarded"
                    )
                selected.append(
                    rng.choice(node.rows, size=len(node.rows), replace=True)
                    if self.design.resample_rows_within_leaf
                    else node.rows
                )

        for stratum in self.strata:
            for index in rng.integers(0, len(stratum), size=len(stratum)):
                visit(self.roots[stratum[int(index)]])
        return np.concatenate(selected)


def plan_sampling(frame: pd.DataFrame, design: SamplingDesign) -> SamplingPlan:
    empty = lambda status: SamplingPlan(
        design, (), (), np.empty(0, dtype=int), frozenset(), status, len(frame)
    )
    if any(column not in frame for column in design.metadata_columns):
        return empty("not_supported_missing_cluster_columns")
    data = frame[list(design.metadata_columns)]
    if data.isna().any().any() or any(
        data[column].astype(str).str.strip().eq("").any() for column in data
    ):
        return empty("not_supported_missing_cluster_ids")
    columns = [
        frame[column].astype(str).to_numpy() for column in design.cluster_columns
    ]
    strata_values = (
        frame[design.strata_column].astype(str).to_numpy()
        if design.strata_column
        else None
    )
    tree, parents, strata = {}, {}, {}
    for row, path in enumerate(zip(*columns)):
        root = path[0]
        if strata_values is not None:
            old = strata.setdefault(root, strata_values[row])
            if old != strata_values[row]:
                return empty("not_supported_nonconstant_cluster_strata")
        node = tree
        for level, label in enumerate(path):
            if level:
                old = parents.setdefault((level, label), path[:level])
                if old != path[:level]:
                    return empty("not_supported_crossed_clusters")
            if level == len(path) - 1:
                node.setdefault(label, []).append(row)
            else:
                node = node.setdefault(label, {})

    def finish(node):
        if isinstance(node, list):
            return _Node((), np.array(node, dtype=int), len(node))
        children = tuple(finish(node[key]) for key in sorted(node))
        return _Node(children, None, sum(child.n_rows for child in children))

    root_ids = sorted(tree)
    roots = tuple(finish(tree[key]) for key in root_ids)
    lookup = {key: index for index, key in enumerate(root_ids)}
    assignments = np.array([lookup[key] for key in columns[0]], dtype=int)
    grouped = {}
    for key, index in lookup.items():
        grouped.setdefault(strata.get(key, "all"), []).append(index)
    blocks = tuple(tuple(grouped[key]) for key in sorted(grouped))
    status = (
        "skipped_min_independent_units"
        if len(roots) < design.min_independent_units
        else (
            "skipped_min_units_per_stratum"
            if any(len(block) < 2 for block in blocks)
            else "evaluated"
        )
    )
    return SamplingPlan(
        design, roots, blocks, assignments, frozenset(root_ids), status, len(frame)
    )


def bootstrap_samples(
    y,
    predictions,
    *,
    task_type,
    metric_names,
    plan: SamplingPlan,
    resamples: int,
    rng: np.random.Generator,
):
    from privatelabbench.eval.uncertainty import _metrics_for_task

    if (
        task_type == "regression"
        and plan.design.method == "cluster_bootstrap"
        and set(metric_names) <= {"mae", "rmse", "r2"}
    ):
        return _cluster_regression_samples(
            y, [predictions], plan=plan, resamples=resamples, rng=rng
        )[0]
    values = {name: np.full(resamples, np.nan, dtype=float) for name in metric_names}
    for index in range(resamples):
        selected = plan.draw(rng)
        scores = _metrics_for_task(task_type, y[selected], predictions[selected])
        for name in metric_names:
            value = float(scores.get(name, float("nan")))
            if math.isfinite(value):
                values[name][index] = value
    return values


def _cluster_regression_samples(
    y, predictions, *, plan: SamplingPlan, resamples: int, rng: np.random.Generator
):
    """Exact cluster sufficient statistics avoid materializing repeated member rows."""
    groups = plan.row_to_root
    count = np.bincount(groups, minlength=plan.n_units)
    centered = y - np.mean(y)
    total_y = np.bincount(groups, weights=centered, minlength=plan.n_units)
    total_y2 = np.bincount(groups, weights=centered * centered, minlength=plan.n_units)
    minima = np.full(plan.n_units, np.inf)
    maxima = np.full(plan.n_units, -np.inf)
    np.minimum.at(minima, groups, y)
    np.maximum.at(maxima, groups, y)
    statistics = []
    output = []
    for prediction in predictions:
        error = y - prediction
        statistics.append(
            (
                np.bincount(groups, weights=np.abs(error), minlength=plan.n_units),
                np.bincount(groups, weights=error * error, minlength=plan.n_units),
            )
        )
        output.append(
            {name: np.full(resamples, np.nan) for name in ("mae", "rmse", "r2")}
        )
    batch_size = max(1, min(256, 2_000_000 // max(plan.n_units, 1)))
    for start in range(0, resamples, batch_size):
        size = min(batch_size, resamples - start)
        draws = np.empty((size, plan.n_units), dtype=int)
        # Keep the same RNG order as whole-cluster draw(), including strata.
        for row in range(size):
            cursor = 0
            for stratum in plan.strata:
                block = np.array(stratum, dtype=int)[
                    rng.integers(0, len(stratum), size=len(stratum))
                ]
                draws[row, cursor : cursor + len(block)] = block
                cursor += len(block)
        n_rows = np.sum(count[draws], axis=1)
        if np.any(n_rows > plan.design.max_resample_rows):
            raise ResampleLimit(
                "Resample row budget exceeded; no tail draws may be silently discarded"
            )
        sum_y = np.sum(total_y[draws], axis=1)
        sum_y2 = np.sum(total_y2[draws], axis=1)
        variance = sum_y2 - sum_y * sum_y / n_rows
        constant = np.min(minima[draws], axis=1) == np.max(maxima[draws], axis=1)
        # Recenter rare tight subsets to avoid cancellation in a widely spread cohort.
        unstable = ~constant & (variance <= 32 * np.finfo(float).eps * sum_y2)
        for row in np.flatnonzero(unstable):
            selected = np.concatenate([plan.roots[index].rows for index in draws[row]])
            subset_y = y[selected]
            variance[row] = np.sum((subset_y - np.mean(subset_y)) ** 2)
        for (absolute, squared), values in zip(statistics, output):
            sse = np.sum(squared[draws], axis=1)
            values["mae"][start : start + size] = (
                np.sum(absolute[draws], axis=1) / n_rows
            )
            values["rmse"][start : start + size] = np.sqrt(sse / n_rows)
            valid = (variance > 0) & ~constant
            r2 = np.full(size, np.nan)
            r2[valid] = 1.0 - sse[valid] / variance[valid]
            values["r2"][start : start + size] = r2
    return output


def adjust_pvalues(
    pvalues: list[float | None], policy: MultiplicityPolicy
) -> list[float | None]:
    """Missing tests stay in the declared family as conservative non-rejections."""
    policy = MultiplicityPolicy.from_dict(policy.as_dict())
    if not pvalues:
        return []
    for value in pvalues:
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise ValueError(
                "Multiplicity correction requires valid p-values between zero and one"
            )
    values = np.array([value if value is not None else 1.0 for value in pvalues])
    order = np.argsort(values, kind="stable")
    factor = (
        math.fsum(1.0 / index for index in range(1, len(values) + 1))
        if policy.method == "benjamini_yekutieli"
        else 1.0
    )
    corrected = np.minimum.accumulate(
        (values[order] * len(values) * factor / np.arange(1, len(values) + 1))[::-1]
    )[::-1]
    result = np.empty(len(values))
    result[order] = np.minimum(corrected, 1.0)
    return [
        None if original is None else float(value)
        for original, value in zip(pvalues, result)
    ]


def metric_intervals(
    y, predictions, *, task_type, config, design: SamplingDesign, metadata: pd.DataFrame
) -> dict[str, Any]:
    from privatelabbench.eval.uncertainty import _interval_entry, _metrics_for_task

    plan = plan_sampling(metadata, design)
    output = {
        **config.as_dict(),
        **plan.metadata(),
        "method": (
            "cluster_percentile_bootstrap"
            if design.method == "cluster_bootstrap"
            else "hierarchical_percentile_bootstrap"
        ),
        "metric_basis": "clean_metrics",
        "metrics": {},
    }
    if design.multiplicity:
        output["multiplicity"] = {
            **design.multiplicity.as_dict(),
            "status": "not_applicable_no_hypothesis_tests",
        }
    status = (
        "disabled"
        if not config.enabled
        else (
            plan.status
            if plan.status != "evaluated"
            else "skipped_min_samples" if len(y) < config.min_samples else "evaluated"
        )
    )
    if status != "evaluated":
        return {**output, "status": status}
    points = _metrics_for_task(task_type, y, predictions)
    try:
        samples = bootstrap_samples(
            y,
            predictions,
            task_type=task_type,
            metric_names=tuple(points),
            plan=plan,
            resamples=config.resamples,
            rng=np.random.default_rng(config.seed),
        )
    except ResampleLimit:
        return {**output, "status": "not_supported_resource_limit"}
    return {
        **output,
        "status": "evaluated",
        "metrics": {
            name: _interval_entry(
                estimate=value,
                values=samples[name],
                confidence_level=config.confidence_level,
                requested_resamples=config.resamples,
            )
            for name, value in points.items()
        },
    }


def paired_interval(
    data, *, metric, direction, config, design: SamplingDesign
) -> dict[str, Any]:
    from privatelabbench.eval.paired_comparison import _metric_at
    from privatelabbench.eval.uncertainty import _interval_entry

    plan = plan_sampling(data.metadata, design)
    output = {
        **plan.metadata(),
        "method": (
            "paired_cluster_percentile_bootstrap"
            if design.method == "cluster_bootstrap"
            else "paired_hierarchical_percentile_bootstrap"
        ),
        "confidence_level": config.confidence_level,
        "resamples": config.resamples,
        "seed": config.seed,
        "metric_basis": "clean_metrics",
    }
    status = (
        plan.status
        if plan.status != "evaluated"
        else (
            "skipped_min_samples"
            if data.n_samples < config.min_samples
            else "evaluated"
        )
    )
    if status != "evaluated":
        return {
            **output,
            "status": status,
            "lower": None,
            "upper": None,
            "valid_resamples": 0,
        }
    rng = np.random.default_rng(config.seed)
    values = np.full(config.resamples, np.nan)
    try:
        if (
            data.task_type == "regression"
            and design.method == "cluster_bootstrap"
            and metric in {"mae", "rmse", "r2"}
        ):
            a, b = _cluster_regression_samples(
                data.y_true,
                [data.predictions_a, data.predictions_b],
                plan=plan,
                resamples=config.resamples,
                rng=rng,
            )
            values = (
                b[metric] - a[metric]
                if direction == "lower_is_better"
                else a[metric] - b[metric]
            )
        else:
            for index in range(config.resamples):
                selected = plan.draw(rng)
                a = _metric_at(
                    data.task_type,
                    metric,
                    data.y_true[selected],
                    data.predictions_a[selected],
                )
                b = _metric_at(
                    data.task_type,
                    metric,
                    data.y_true[selected],
                    data.predictions_b[selected],
                )
                values[index] = b - a if direction == "lower_is_better" else a - b
    except ResampleLimit:
        return {
            **output,
            "status": "not_supported_resource_limit",
            "lower": None,
            "upper": None,
            "valid_resamples": 0,
        }
    observed_a = _metric_at(data.task_type, metric, data.y_true, data.predictions_a)
    observed_b = _metric_at(data.task_type, metric, data.y_true, data.predictions_b)
    estimate = (
        observed_b - observed_a
        if direction == "lower_is_better"
        else observed_a - observed_b
    )
    return {
        **output,
        **_interval_entry(
            estimate=estimate,
            values=values,
            confidence_level=config.confidence_level,
            requested_resamples=config.resamples,
        ),
    }


def paired_randomization(
    data, *, metric, direction, observed_improvement, config, design: SamplingDesign
) -> dict[str, Any]:
    from privatelabbench.eval.paired_comparison import _metric_at

    plan = plan_sampling(data.metadata, design)
    output = {
        **plan.metadata(),
        "method": "paired_cluster_randomization_swap",
        "alternative": "two_sided",
        "permutations": config.permutations,
        "seed": config.seed + 1,
        "p_value": None,
        "valid_permutations": 0,
    }
    status = (
        "disabled"
        if config.permutations == 0
        else (
            plan.status
            if plan.status != "evaluated"
            else (
                "skipped_min_samples"
                if data.n_samples < config.min_samples
                else (
                    "not_supported_resource_limit"
                    if data.n_samples > design.max_resample_rows
                    else (
                        "not_supported_nested_permutation"
                        if design.method != "cluster_bootstrap"
                        else (
                            "exchangeability_not_declared"
                            if design.exchangeability != "model_vectors_within_clusters"
                            else "evaluated"
                        )
                    )
                )
            )
        )
    )
    if status != "evaluated":
        return {**output, "status": status}
    rng = np.random.default_rng(config.seed + 1)
    extreme = valid = 0
    for _ in range(config.permutations):
        selected = (rng.random(plan.n_units) < 0.5)[plan.row_to_root]
        mask = selected if data.predictions_a.ndim == 1 else selected[:, None]
        a = _metric_at(
            data.task_type,
            metric,
            data.y_true,
            np.where(mask, data.predictions_b, data.predictions_a),
        )
        b = _metric_at(
            data.task_type,
            metric,
            data.y_true,
            np.where(mask, data.predictions_a, data.predictions_b),
        )
        improvement = b - a if direction == "lower_is_better" else a - b
        if math.isfinite(improvement):
            valid += 1
            extreme += abs(improvement) >= abs(observed_improvement) - 1e-15
    if valid < max(20, math.ceil(config.permutations * 0.8)):
        return {
            **output,
            "status": "insufficient_valid_permutations",
            "valid_permutations": valid,
        }
    return {
        **output,
        "status": "evaluated",
        "p_value": (int(extreme) + 1) / (valid + 1),
        "valid_permutations": valid,
    }


def apply_multiplicity(
    slices: dict[str, Any], design: SamplingDesign
) -> dict[str, Any]:
    policy = design.multiplicity
    if policy is None:
        return {}
    critical = set(design.critical_slices)
    for column, value in critical:
        slices.setdefault(column, {}).setdefault(
            value, {"n": 0, "status": "missing_prespecified_slice"}
        )
    selected = []
    for column, groups in slices.items():
        for value, entry in groups.items():
            prescribed = (column, value) in critical
            entry["inference_role"] = (
                "prespecified_critical" if prescribed else "exploratory"
            )
            if prescribed == (policy.family == "critical_slices"):
                test = entry.get("randomization_test", {})
                p = test.get("p_value") if test.get("status") == "evaluated" else None
                selected.append((entry, p))
    adjusted = adjust_pvalues([p for entry, p in selected], policy)
    for (entry, raw), value in zip(selected, adjusted):
        entry["multiplicity"] = {
            **policy.as_dict(),
            "raw_p_value": raw,
            "adjusted_p_value": value,
            "reject": value <= policy.alpha if value is not None else None,
            "status": "evaluated" if value is not None else "not_testable",
        }
    return {
        **policy.as_dict(),
        "n_tests": len(selected),
        "n_usable_tests": sum(p is not None for entry, p in selected),
        "n_missing_tests": sum(p is None for entry, p in selected),
        "status": (
            "evaluated"
            if any(p is not None for entry, p in selected)
            else "not_testable"
        ),
        "limitations": [
            "Adjusted p-values require valid input tests and the declared dependence assumptions.",
            "Test families and critical slices must be fixed before inspecting outcomes.",
            "Missing tests remain in the family as conservative non-rejections.",
            "Adjusted p-values do not establish causality or practical usefulness.",
        ],
    }
