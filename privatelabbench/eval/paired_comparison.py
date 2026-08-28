from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from privatelabbench.eval.metrics import classification_metrics, multiclass_metrics, regression_metrics
from privatelabbench.tasks.molecules import infer_task_type


PAIRED_COMPARISON_SCHEMA_VERSION = "paired-comparison/v1"
LOWER_IS_BETTER = frozenset({"mae", "rmse", "log_loss"})


@dataclass(frozen=True)
class PairedComparisonConfig:
    metric: str | None = None
    confidence_level: float = 0.95
    resamples: int = 1000
    permutations: int = 1000
    seed: int = 13
    min_samples: int = 20
    practical_threshold: float = 0.0
    noninferiority_margin: float | None = None
    include_slice_uncertainty: bool = False
    min_slice_size: int = 5

    def validate(self) -> None:
        if not 0.0 < self.confidence_level < 1.0:
            raise ValueError("confidence_level must be between 0 and 1")
        if self.resamples < 100:
            raise ValueError("resamples must be at least 100")
        if self.permutations != 0 and self.permutations < 100:
            raise ValueError("permutations must be 0 or at least 100")
        if self.min_samples < 2:
            raise ValueError("min_samples must be at least 2")
        if self.min_slice_size < 1:
            raise ValueError("min_slice_size must be at least 1")
        if self.practical_threshold < 0.0:
            raise ValueError("practical_threshold must be non-negative")
        if self.noninferiority_margin is not None and self.noninferiority_margin < 0.0:
            raise ValueError("noninferiority_margin must be non-negative")


@dataclass(frozen=True)
class _AlignedTables:
    y_true: np.ndarray
    predictions_a: np.ndarray
    predictions_b: np.ndarray
    task_type: str
    class_labels: tuple[str, ...]
    metadata: pd.DataFrame
    n_samples: int


def _prediction_columns(
    *,
    prediction_column: str | None,
    prediction_columns: Sequence[str] | None,
) -> tuple[str, ...]:
    multi = tuple(str(value).strip() for value in (prediction_columns or ()))
    single = str(prediction_column).strip() if prediction_column else ""
    if single and multi:
        raise ValueError("Use either prediction_column or prediction_columns, not both")
    if single:
        return (single,)
    if multi:
        if any(not value for value in multi):
            raise ValueError("prediction_columns cannot contain empty names")
        if len(set(multi)) != len(multi):
            raise ValueError("prediction_columns cannot contain duplicates")
        return multi
    return ("prediction",)


def _validate_ids(df: pd.DataFrame, *, sample_id_column: str, label: str) -> None:
    if sample_id_column not in df.columns:
        raise ValueError(f"{label} is missing sample ID column '{sample_id_column}'")
    ids = df[sample_id_column]
    if ids.isna().any() or ids.astype(str).str.strip().eq("").any():
        raise ValueError(f"{label} sample ID column '{sample_id_column}' contains missing/empty values")
    duplicated = ids[ids.duplicated()].astype(str).head(3).tolist()
    if duplicated:
        raise ValueError(f"{label} contains duplicate sample IDs: {', '.join(duplicated)}")


def _equal_series(left: pd.Series, right: pd.Series) -> np.ndarray:
    left_numeric = pd.to_numeric(left, errors="coerce")
    right_numeric = pd.to_numeric(right, errors="coerce")
    numeric = left_numeric.notna() & right_numeric.notna()
    equal = np.zeros(len(left), dtype=bool)
    if numeric.any():
        mask = numeric.to_numpy()
        equal[mask] = np.isclose(
            left_numeric[numeric].to_numpy(dtype=float),
            right_numeric[numeric].to_numpy(dtype=float),
            equal_nan=True,
        )
    non_numeric = ~numeric
    if non_numeric.any():
        mask = non_numeric.to_numpy()
        equal[mask] = (
            left[non_numeric].astype("string").fillna("<NA>").to_numpy()
            == right[non_numeric].astype("string").fillna("<NA>").to_numpy()
        )
    return equal


def _resolve_task_type(
    task_type: str | None,
    targets: np.ndarray,
    prediction_columns: tuple[str, ...],
) -> str:
    if task_type:
        resolved = str(task_type).strip().lower()
    elif len(prediction_columns) > 1:
        resolved = "multiclass"
    else:
        try:
            resolved = infer_task_type(targets.astype(float))
        except (TypeError, ValueError):
            resolved = "classification" if len(pd.unique(targets)) == 2 else "multiclass"
    if resolved not in {"regression", "classification", "multiclass"}:
        raise ValueError("task_type must be regression, classification, or multiclass")
    if resolved == "multiclass" and len(prediction_columns) < 2:
        raise ValueError("multiclass comparison requires multiple probability columns")
    if resolved != "multiclass" and len(prediction_columns) != 1:
        raise ValueError(f"{resolved} comparison requires exactly one prediction column")
    return resolved


def _default_labels(targets: np.ndarray) -> tuple[str, ...]:
    # Deterministic ordering matters because the single binary score is interpreted
    # as the probability of the second class.
    return tuple(sorted({str(value) for value in targets}))


def _encode_targets(
    targets: np.ndarray,
    *,
    task_type: str,
    class_labels: Sequence[str] | None,
    n_prediction_columns: int,
) -> tuple[np.ndarray, tuple[str, ...]]:
    if task_type == "regression":
        try:
            return targets.astype(float), ()
        except (TypeError, ValueError) as exc:
            raise ValueError("Regression targets must be numeric") from exc

    labels = tuple(str(value) for value in class_labels) if class_labels else _default_labels(targets)
    expected = 2 if task_type == "classification" else n_prediction_columns
    if len(labels) != expected or len(set(labels)) != len(labels):
        raise ValueError(f"{task_type} comparison requires exactly {expected} unique class labels")
    mapping = {label: index for index, label in enumerate(labels)}
    unknown = sorted({str(value) for value in targets if str(value) not in mapping})
    if unknown:
        raise ValueError(f"Target contains labels not present in class_labels: {', '.join(unknown)}")
    return np.asarray([mapping[str(value)] for value in targets], dtype=int), labels


def _numeric_predictions(
    df: pd.DataFrame,
    columns: tuple[str, ...],
    *,
    label: str,
) -> np.ndarray:
    try:
        values = df[list(columns)].astype(float).to_numpy()
    except ValueError as exc:
        raise ValueError(f"{label} prediction columns must be numeric") from exc
    if not np.all(np.isfinite(values)):
        raise ValueError(f"{label} prediction columns contain non-finite values")
    if len(columns) == 1:
        return values[:, 0]
    if np.any(values < 0.0) or np.any(values > 1.0):
        raise ValueError(f"{label} multiclass probabilities must be between 0 and 1")
    if not np.allclose(values.sum(axis=1), 1.0, atol=1e-4):
        raise ValueError(f"{label} multiclass probability rows must sum to 1.0")
    return values


def _load_aligned_tables(
    path_a: str,
    path_b: str,
    *,
    target: str,
    prediction_column: str | None,
    prediction_columns: Sequence[str] | None,
    sample_id_column: str,
    task_type: str | None,
    class_labels: Sequence[str] | None,
    slice_columns: Sequence[str] | None,
) -> _AlignedTables:
    prediction_cols = _prediction_columns(
        prediction_column=prediction_column,
        prediction_columns=prediction_columns,
    )
    slices = tuple(str(column) for column in (slice_columns or ()))
    if len(set(slices)) != len(slices):
        raise ValueError("slice_columns cannot contain duplicates")
    required = {sample_id_column, target, *prediction_cols, *slices}
    dtype = {sample_id_column: "string"}
    a = pd.read_csv(path_a, dtype=dtype)
    b = pd.read_csv(path_b, dtype=dtype)

    for frame, label in ((a, "Model A table"), (b, "Model B table")):
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{label} is missing required column(s): {', '.join(sorted(missing))}")
        _validate_ids(frame, sample_id_column=sample_id_column, label=label)
        if frame[target].isna().any() or frame[list(prediction_cols)].isna().any().any():
            raise ValueError(
                f"{label} contains missing targets or predictions; paired comparison does not drop rows"
            )

    ids_a = a[sample_id_column].astype(str)
    ids_b = b[sample_id_column].astype(str)
    set_a, set_b = set(ids_a), set(ids_b)
    if set_a != set_b:
        only_a = sorted(set_a - set_b)[:3]
        only_b = sorted(set_b - set_a)[:3]
        raise ValueError(
            "Prediction tables must contain exactly the same sample IDs; "
            f"only in A={len(set_a - set_b)} {only_a}, "
            f"only in B={len(set_b - set_a)} {only_b}"
        )

    a = a.set_index(sample_id_column, drop=False)
    b = b.set_index(sample_id_column, drop=False).loc[a.index]
    target_equal = _equal_series(a[target], b[target])
    if not bool(np.all(target_equal)):
        mismatches = a.index[~target_equal].astype(str).tolist()[:3]
        raise ValueError(
            f"Targets disagree between prediction tables for sample ID(s): {', '.join(mismatches)}"
        )
    for column in slices:
        equal = _equal_series(a[column], b[column])
        if not bool(np.all(equal)):
            mismatches = a.index[~equal].astype(str).tolist()[:3]
            raise ValueError(
                f"Slice metadata column '{column}' disagrees between prediction tables "
                f"for sample ID(s): {', '.join(mismatches)}"
            )

    raw_targets = a[target].to_numpy()
    resolved_task = _resolve_task_type(task_type, raw_targets, prediction_cols)
    encoded_targets, labels = _encode_targets(
        raw_targets,
        task_type=resolved_task,
        class_labels=class_labels,
        n_prediction_columns=len(prediction_cols),
    )
    predictions_a = _numeric_predictions(a, prediction_cols, label="Model A")
    predictions_b = _numeric_predictions(b, prediction_cols, label="Model B")
    if resolved_task == "classification":
        for values, label in ((predictions_a, "Model A"), (predictions_b, "Model B")):
            if np.any(values < 0.0) or np.any(values > 1.0):
                raise ValueError(f"{label} binary probabilities must be between 0 and 1")

    metadata = (
        a[list(slices)].reset_index(drop=True)
        if slices
        else pd.DataFrame(index=range(len(a)))
    )
    return _AlignedTables(
        y_true=encoded_targets,
        predictions_a=predictions_a,
        predictions_b=predictions_b,
        task_type=resolved_task,
        class_labels=labels,
        metadata=metadata,
        n_samples=len(a),
    )


def _metric_values(
    task_type: str,
    y_true: np.ndarray,
    predictions: np.ndarray,
) -> dict[str, float]:
    if task_type == "regression":
        return regression_metrics(y_true.astype(float), predictions.astype(float))
    if task_type == "classification":
        return classification_metrics(y_true.astype(int), predictions.astype(float))
    return multiclass_metrics(
        y_true.astype(int),
        predictions.astype(float),
        labels=list(range(predictions.shape[1])),
    )


def _default_metric(task_type: str) -> str:
    return {
        "regression": "rmse",
        "classification": "auroc",
        "multiclass": "macro_auroc_ovr",
    }[task_type]


def _direction(metric: str) -> str:
    return "lower_is_better" if metric in LOWER_IS_BETTER else "higher_is_better"


def _improvement(value_a: float, value_b: float, *, direction: str) -> float:
    # Positive always means A is better.
    return value_b - value_a if direction == "lower_is_better" else value_a - value_b


def _stratified_indices(y_true: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    parts = []
    for label in np.unique(y_true):
        indices = np.flatnonzero(y_true == label)
        parts.append(rng.choice(indices, size=len(indices), replace=True))
    result = np.concatenate(parts)
    rng.shuffle(result)
    return result


def _metric_at(
    task_type: str,
    metric: str,
    y_true: np.ndarray,
    predictions: np.ndarray,
) -> float:
    return float(_metric_values(task_type, y_true, predictions).get(metric, float("nan")))


def _regression_metric_batch(
    metric: str,
    y_true: np.ndarray,
    predictions: np.ndarray,
) -> np.ndarray:
    residual = y_true - predictions
    if metric == "mae":
        return np.mean(np.abs(residual), axis=1)
    if metric == "rmse":
        return np.sqrt(np.mean(residual * residual, axis=1))
    if metric == "r2":
        centered = y_true - np.mean(y_true, axis=1, keepdims=True)
        denominator = np.sum(centered * centered, axis=1)
        numerator = np.sum(residual * residual, axis=1)
        values = np.full(len(y_true), np.nan, dtype=float)
        valid = denominator > 0.0
        values[valid] = 1.0 - numerator[valid] / denominator[valid]
        return values
    raise ValueError(f"Unsupported regression comparison metric: {metric}")


def _regression_bootstrap_improvements(
    y_true: np.ndarray,
    predictions_a: np.ndarray,
    predictions_b: np.ndarray,
    *,
    metric: str,
    resamples: int,
    rng: np.random.Generator,
) -> np.ndarray:
    n = len(y_true)
    output = np.full(resamples, np.nan, dtype=float)
    batch_size = max(1, min(256, 2_000_000 // max(n, 1)))
    cursor = 0
    while cursor < resamples:
        size = min(batch_size, resamples - cursor)
        indices = rng.integers(0, n, size=(size, n))
        y = y_true[indices]
        metric_a = _regression_metric_batch(metric, y, predictions_a[indices])
        metric_b = _regression_metric_batch(metric, y, predictions_b[indices])
        direction = _direction(metric)
        batch = (
            metric_b - metric_a
            if direction == "lower_is_better"
            else metric_a - metric_b
        )
        output[cursor : cursor + size] = batch
        cursor += size
    return output


def _bootstrap_improvements(
    data: _AlignedTables,
    *,
    metric: str,
    direction: str,
    config: PairedComparisonConfig,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "method": "paired_percentile_bootstrap",
        "confidence_level": config.confidence_level,
        "resamples": config.resamples,
        "seed": config.seed,
        "sampling": "iid_rows" if data.task_type == "regression" else "stratified_by_target",
        "n_samples": data.n_samples,
    }
    if data.n_samples < config.min_samples:
        return {
            **metadata,
            "status": "skipped_min_samples",
            "lower": None,
            "upper": None,
            "valid_resamples": 0,
        }

    rng = np.random.default_rng(config.seed)
    if data.task_type == "regression":
        values = _regression_bootstrap_improvements(
            data.y_true,
            data.predictions_a,
            data.predictions_b,
            metric=metric,
            resamples=config.resamples,
            rng=rng,
        )
    else:
        values = np.full(config.resamples, np.nan, dtype=float)
        for index in range(config.resamples):
            indices = _stratified_indices(data.y_true, rng)
            value_a = _metric_at(
                data.task_type, metric, data.y_true[indices], data.predictions_a[indices]
            )
            value_b = _metric_at(
                data.task_type, metric, data.y_true[indices], data.predictions_b[indices]
            )
            if math.isfinite(value_a) and math.isfinite(value_b):
                values[index] = _improvement(value_a, value_b, direction=direction)

    finite = values[np.isfinite(values)]
    minimum_valid = max(20, math.ceil(config.resamples * 0.8))
    if len(finite) < minimum_valid:
        return {
            **metadata,
            "status": "insufficient_valid_resamples",
            "lower": None,
            "upper": None,
            "valid_resamples": int(len(finite)),
        }
    alpha = 1.0 - config.confidence_level
    lower, upper = np.quantile(finite, [alpha / 2.0, 1.0 - alpha / 2.0])
    return {
        **metadata,
        "status": "evaluated",
        "lower": float(lower),
        "upper": float(upper),
        "valid_resamples": int(len(finite)),
    }


def _regression_randomization_improvements(
    data: _AlignedTables,
    *,
    metric: str,
    permutations: int,
    rng: np.random.Generator,
) -> np.ndarray:
    n = data.n_samples
    output = np.full(permutations, np.nan, dtype=float)
    batch_size = max(1, min(256, 2_000_000 // max(n, 1)))
    cursor = 0
    while cursor < permutations:
        size = min(batch_size, permutations - cursor)
        swap = rng.random((size, n)) < 0.5
        a = np.broadcast_to(data.predictions_a, (size, n))
        b = np.broadcast_to(data.predictions_b, (size, n))
        perm_a = np.where(swap, b, a)
        perm_b = np.where(swap, a, b)
        y = np.broadcast_to(data.y_true, (size, n))
        metric_a = _regression_metric_batch(metric, y, perm_a)
        metric_b = _regression_metric_batch(metric, y, perm_b)
        direction = _direction(metric)
        output[cursor : cursor + size] = (
            metric_b - metric_a
            if direction == "lower_is_better"
            else metric_a - metric_b
        )
        cursor += size
    return output


def _randomization_test(
    data: _AlignedTables,
    *,
    metric: str,
    direction: str,
    observed_improvement: float,
    config: PairedComparisonConfig,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "method": "paired_randomization_swap",
        "alternative": "two_sided",
        "permutations": config.permutations,
        "seed": config.seed + 1,
    }
    if config.permutations == 0:
        return {**metadata, "status": "disabled", "p_value": None}
    if data.n_samples < config.min_samples:
        return {**metadata, "status": "skipped_min_samples", "p_value": None}

    rng = np.random.default_rng(config.seed + 1)
    if data.task_type == "regression":
        values = _regression_randomization_improvements(
            data,
            metric=metric,
            permutations=config.permutations,
            rng=rng,
        )
        finite = values[np.isfinite(values)]
        if len(finite) == 0:
            return {
                **metadata,
                "status": "unavailable",
                "p_value": None,
                "valid_permutations": 0,
            }
        extreme = int(np.count_nonzero(np.abs(finite) >= abs(observed_improvement) - 1e-15))
        return {
            **metadata,
            "status": "evaluated",
            "p_value": float((extreme + 1) / (len(finite) + 1)),
            "valid_permutations": int(len(finite)),
        }

    extreme = 0
    valid = 0
    for _ in range(config.permutations):
        swap = rng.random(data.n_samples) < 0.5
        if data.predictions_a.ndim == 1:
            perm_a = np.where(swap, data.predictions_b, data.predictions_a)
            perm_b = np.where(swap, data.predictions_a, data.predictions_b)
        else:
            mask = swap[:, None]
            perm_a = np.where(mask, data.predictions_b, data.predictions_a)
            perm_b = np.where(mask, data.predictions_a, data.predictions_b)
        value_a = _metric_at(data.task_type, metric, data.y_true, perm_a)
        value_b = _metric_at(data.task_type, metric, data.y_true, perm_b)
        if not (math.isfinite(value_a) and math.isfinite(value_b)):
            continue
        null_improvement = _improvement(value_a, value_b, direction=direction)
        valid += 1
        if abs(null_improvement) >= abs(observed_improvement) - 1e-15:
            extreme += 1
    if valid == 0:
        return {
            **metadata,
            "status": "unavailable",
            "p_value": None,
            "valid_permutations": 0,
        }
    return {
        **metadata,
        "status": "evaluated",
        "p_value": float((extreme + 1) / (valid + 1)),
        "valid_permutations": valid,
    }


def _decisions(
    *,
    improvement: float,
    interval: Mapping[str, object],
    config: PairedComparisonConfig,
) -> dict[str, object]:
    threshold = config.practical_threshold
    if threshold == 0.0:
        point = (
            "a_above_threshold"
            if improvement > 0.0
            else "b_above_threshold"
            if improvement < 0.0
            else "below_practical_threshold"
        )
    else:
        point = (
            "a_above_threshold"
            if improvement >= threshold
            else "b_above_threshold"
            if improvement <= -threshold
            else "below_practical_threshold"
        )

    confidence = "insufficient_evidence"
    lower = interval.get("lower")
    upper = interval.get("upper")
    if interval.get("status") == "evaluated" and lower is not None and upper is not None:
        lower_value = float(lower)
        upper_value = float(upper)
        if threshold == 0.0:
            if lower_value > 0.0:
                confidence = "a_exceeds_threshold"
            elif upper_value < 0.0:
                confidence = "b_exceeds_threshold"
            else:
                confidence = "inconclusive"
        elif lower_value >= threshold:
            confidence = "a_exceeds_threshold"
        elif upper_value <= -threshold:
            confidence = "b_exceeds_threshold"
        else:
            confidence = "inconclusive"

    noninferiority: dict[str, object] | None = None
    if config.noninferiority_margin is not None:
        margin = config.noninferiority_margin
        status = "insufficient_evidence"
        if interval.get("status") == "evaluated" and lower is not None:
            status = (
                "a_noninferior"
                if float(lower) >= -margin
                else "noninferiority_not_established"
            )
        noninferiority = {"margin": margin, "status": status}
    return {
        "practical_threshold": threshold,
        "point_estimate": point,
        "confidence_interval": confidence,
        "noninferiority": noninferiority,
    }


def _slice_results(
    data: _AlignedTables,
    *,
    metric: str,
    direction: str,
    slice_columns: Sequence[str] | None,
    config: PairedComparisonConfig,
) -> dict[str, dict[str, dict[str, object]]]:
    results: dict[str, dict[str, dict[str, object]]] = {}
    slice_seed = 0
    for column in slice_columns or ():
        groups: dict[str, dict[str, object]] = {}
        for value, indices in data.metadata.groupby(column, dropna=False, sort=True).indices.items():
            idx = np.asarray(indices, dtype=int)
            key = "<NA>" if pd.isna(value) else str(value)
            entry: dict[str, object] = {"n": int(len(idx))}
            if len(idx) < config.min_slice_size:
                entry["status"] = "skipped_min_slice_size"
                groups[key] = entry
                continue

            subset = _AlignedTables(
                y_true=data.y_true[idx],
                predictions_a=data.predictions_a[idx],
                predictions_b=data.predictions_b[idx],
                task_type=data.task_type,
                class_labels=data.class_labels,
                metadata=data.metadata.iloc[idx].reset_index(drop=True),
                n_samples=len(idx),
            )
            metrics_a = _metric_values(data.task_type, subset.y_true, subset.predictions_a)
            metrics_b = _metric_values(data.task_type, subset.y_true, subset.predictions_b)
            value_a = float(metrics_a[metric])
            value_b = float(metrics_b[metric])
            if not (math.isfinite(value_a) and math.isfinite(value_b)):
                entry.update(
                    {
                        "status": "metric_undefined",
                        "metric_a": value_a,
                        "metric_b": value_b,
                    }
                )
                groups[key] = entry
                continue

            improvement = _improvement(value_a, value_b, direction=direction)
            entry.update(
                {
                    "status": "evaluated",
                    "metric_a": value_a,
                    "metric_b": value_b,
                    "improvement": improvement,
                    "winner": "a" if improvement > 0 else "b" if improvement < 0 else "tie",
                }
            )
            if config.include_slice_uncertainty:
                slice_seed += 1
                slice_config = PairedComparisonConfig(
                    metric=metric,
                    confidence_level=config.confidence_level,
                    resamples=config.resamples,
                    permutations=0,
                    seed=config.seed + slice_seed,
                    min_samples=config.min_samples,
                    practical_threshold=config.practical_threshold,
                    noninferiority_margin=config.noninferiority_margin,
                    include_slice_uncertainty=False,
                    min_slice_size=config.min_slice_size,
                )
                entry["paired_interval"] = _bootstrap_improvements(
                    subset,
                    metric=metric,
                    direction=direction,
                    config=slice_config,
                )
            groups[key] = entry
        results[str(column)] = groups
    return results


def compare_prediction_tables(
    path_a: str,
    path_b: str,
    *,
    target: str,
    prediction_column: str | None = "prediction",
    prediction_columns: Sequence[str] | None = None,
    sample_id_column: str = "sample_id",
    task_type: str | None = None,
    class_labels: Sequence[str] | None = None,
    slice_columns: Sequence[str] | None = None,
    model_a_name: str | None = None,
    model_b_name: str | None = None,
    config: PairedComparisonConfig | None = None,
) -> dict[str, Any]:
    resolved_config = config or PairedComparisonConfig()
    resolved_config.validate()
    data = _load_aligned_tables(
        path_a,
        path_b,
        target=target,
        prediction_column=prediction_column,
        prediction_columns=prediction_columns,
        sample_id_column=sample_id_column,
        task_type=task_type,
        class_labels=class_labels,
        slice_columns=slice_columns,
    )
    metrics_a = _metric_values(data.task_type, data.y_true, data.predictions_a)
    metrics_b = _metric_values(data.task_type, data.y_true, data.predictions_b)
    metric = resolved_config.metric or _default_metric(data.task_type)
    if metric not in metrics_a or metric not in metrics_b:
        available = ", ".join(sorted(set(metrics_a) & set(metrics_b)))
        raise ValueError(
            f"Metric '{metric}' is not available for {data.task_type}; choose one of: {available}"
        )
    value_a = float(metrics_a[metric])
    value_b = float(metrics_b[metric])
    if not (math.isfinite(value_a) and math.isfinite(value_b)):
        raise ValueError(f"Metric '{metric}' is undefined on the aligned evaluation data")

    direction = _direction(metric)
    raw_delta = value_a - value_b
    improvement = _improvement(value_a, value_b, direction=direction)
    interval = _bootstrap_improvements(
        data,
        metric=metric,
        direction=direction,
        config=resolved_config,
    )
    interval["estimate"] = improvement
    randomization = _randomization_test(
        data,
        metric=metric,
        direction=direction,
        observed_improvement=improvement,
        config=resolved_config,
    )
    return {
        "schema_version": PAIRED_COMPARISON_SCHEMA_VERSION,
        "task_type": data.task_type,
        "class_labels": list(data.class_labels),
        "sample_id_column": sample_id_column,
        "target_column": target,
        "n_samples": data.n_samples,
        "alignment": {
            "status": "exact_sample_id_match",
            "n_model_a": data.n_samples,
            "n_model_b": data.n_samples,
            "dropped_samples": 0,
        },
        "model_a": {
            "name": model_a_name or Path(path_a).stem,
            "metrics": metrics_a,
            "selected_metric": value_a,
        },
        "model_b": {
            "name": model_b_name or Path(path_b).stem,
            "metrics": metrics_b,
            "selected_metric": value_b,
        },
        "metric": metric,
        "direction": direction,
        "raw_delta_a_minus_b": raw_delta,
        "improvement_a_over_b": improvement,
        "paired_interval": interval,
        "randomization_test": randomization,
        "decision": _decisions(
            improvement=improvement,
            interval=interval,
            config=resolved_config,
        ),
        "slices": _slice_results(
            data,
            metric=metric,
            direction=direction,
            slice_columns=slice_columns,
            config=resolved_config,
        ),
    }
