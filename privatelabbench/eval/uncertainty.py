from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Iterator

import numpy as np

from privatelabbench.eval.metrics import classification_metrics, multiclass_metrics, regression_metrics


UNCERTAINTY_SCHEMA_VERSION = "uncertainty/v1"


@dataclass(frozen=True)
class BootstrapConfig:
    """Configuration for reproducible percentile-bootstrap uncertainty estimates."""

    enabled: bool = False
    confidence_level: float = 0.95
    resamples: int = 1000
    seed: int = 13
    min_samples: int = 20
    include_slices: bool = False
    method: str = "percentile_bootstrap"

    def validate(self) -> None:
        if self.method != "percentile_bootstrap":
            raise ValueError("uncertainty.method must be 'percentile_bootstrap'")
        if not 0.0 < self.confidence_level < 1.0:
            raise ValueError("uncertainty.confidence_level must be between 0 and 1")
        if self.resamples < 100:
            raise ValueError("uncertainty.resamples must be at least 100")
        if self.min_samples < 2:
            raise ValueError("uncertainty.min_samples must be at least 2")

    def for_slice(self, *, seed_offset: int) -> BootstrapConfig:
        return replace(self, seed=self.seed + seed_offset, include_slices=False)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": UNCERTAINTY_SCHEMA_VERSION,
            "enabled": self.enabled,
            "method": self.method,
            "confidence_level": self.confidence_level,
            "resamples": self.resamples,
            "seed": self.seed,
            "min_samples": self.min_samples,
            "include_slices": self.include_slices,
        }


def _metrics_for_task(task_type: str, y_true: np.ndarray, predictions: np.ndarray) -> dict[str, float]:
    if task_type == "regression":
        return regression_metrics(y_true.astype(float), predictions.astype(float))
    if task_type == "classification":
        return classification_metrics(y_true.astype(int), predictions.astype(float))
    if task_type == "multiclass":
        return multiclass_metrics(
            y_true.astype(int),
            predictions.astype(float),
            labels=list(range(predictions.shape[1])),
        )
    raise ValueError(f"Unsupported task type for uncertainty estimation: {task_type}")


def _stratified_indices(y_true: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    pieces = []
    for label in np.unique(y_true):
        class_indices = np.flatnonzero(y_true == label)
        pieces.append(rng.choice(class_indices, size=len(class_indices), replace=True))
    indices = np.concatenate(pieces)
    rng.shuffle(indices)
    return indices


def _resample_indices(
    y_true: np.ndarray,
    *,
    task_type: str,
    resamples: int,
    rng: np.random.Generator,
) -> Iterator[np.ndarray]:
    n_samples = len(y_true)
    if task_type == "regression":
        for _ in range(resamples):
            yield rng.integers(0, n_samples, size=n_samples)
        return
    for _ in range(resamples):
        yield _stratified_indices(y_true, rng)


def _regression_bootstrap_values(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    *,
    resamples: int,
    rng: np.random.Generator,
) -> dict[str, np.ndarray]:
    """Vectorized regression bootstrap with bounded temporary memory."""

    n_samples = len(y_true)
    values = {
        "mae": np.empty(resamples, dtype=float),
        "rmse": np.empty(resamples, dtype=float),
        "r2": np.empty(resamples, dtype=float),
    }
    batch_size = max(1, min(256, 2_000_000 // max(n_samples, 1)))
    cursor = 0
    while cursor < resamples:
        size = min(batch_size, resamples - cursor)
        indices = rng.integers(0, n_samples, size=(size, n_samples))
        sampled_true = y_true[indices]
        sampled_pred = y_pred[indices]
        residual = sampled_true - sampled_pred
        values["mae"][cursor : cursor + size] = np.mean(np.abs(residual), axis=1)
        values["rmse"][cursor : cursor + size] = np.sqrt(np.mean(residual * residual, axis=1))
        centered = sampled_true - np.mean(sampled_true, axis=1, keepdims=True)
        denominator = np.sum(centered * centered, axis=1)
        numerator = np.sum(residual * residual, axis=1)
        r2 = np.full(size, np.nan, dtype=float)
        valid = denominator > 0.0
        r2[valid] = 1.0 - numerator[valid] / denominator[valid]
        values["r2"][cursor : cursor + size] = r2
        cursor += size
    return values


def _generic_bootstrap_values(
    y_true: np.ndarray,
    predictions: np.ndarray,
    *,
    task_type: str,
    metric_names: tuple[str, ...],
    resamples: int,
    rng: np.random.Generator,
) -> dict[str, np.ndarray]:
    values = {name: np.full(resamples, np.nan, dtype=float) for name in metric_names}
    for index, sample_indices in enumerate(
        _resample_indices(y_true, task_type=task_type, resamples=resamples, rng=rng)
    ):
        sample_predictions = predictions[sample_indices]
        sample_metrics = _metrics_for_task(task_type, y_true[sample_indices], sample_predictions)
        for name in metric_names:
            value = float(sample_metrics.get(name, float("nan")))
            if math.isfinite(value):
                values[name][index] = value
    return values


def _interval_entry(
    *,
    estimate: float,
    values: np.ndarray,
    confidence_level: float,
    requested_resamples: int,
) -> dict[str, object]:
    finite = values[np.isfinite(values)]
    minimum_valid = max(20, math.ceil(requested_resamples * 0.8))
    estimate_value: float | None = float(estimate) if math.isfinite(float(estimate)) else None
    if estimate_value is None:
        return {
            "estimate": None,
            "lower": None,
            "upper": None,
            "valid_resamples": int(len(finite)),
            "status": "undefined_point_estimate",
        }
    if len(finite) < minimum_valid:
        return {
            "estimate": estimate_value,
            "lower": None,
            "upper": None,
            "valid_resamples": int(len(finite)),
            "status": "insufficient_valid_resamples",
        }
    alpha = 1.0 - confidence_level
    lower, upper = np.quantile(finite, [alpha / 2.0, 1.0 - alpha / 2.0])
    return {
        "estimate": estimate_value,
        "lower": float(lower),
        "upper": float(upper),
        "valid_resamples": int(len(finite)),
        "status": "evaluated",
    }


def bootstrap_metric_intervals(
    *,
    task_type: str,
    y_true: np.ndarray,
    predictions: np.ndarray,
    config: BootstrapConfig,
) -> dict[str, object]:
    """Estimate aggregate metric uncertainty without returning row-level values."""

    config.validate()
    if not config.enabled:
        return {}

    n_samples = int(len(y_true))
    sampling = "iid_rows" if task_type == "regression" else "stratified_by_target"
    metadata: dict[str, object] = {
        **config.as_dict(),
        "metric_basis": "clean_metrics",
        "sampling": sampling,
        "n_samples": n_samples,
    }
    if n_samples < config.min_samples:
        return {**metadata, "status": "skipped_min_samples", "metrics": {}}

    point_metrics = _metrics_for_task(task_type, y_true, predictions)
    metric_names = tuple(point_metrics)
    rng = np.random.default_rng(config.seed)
    if task_type == "regression":
        bootstrap_values = _regression_bootstrap_values(
            y_true.astype(float),
            predictions.astype(float),
            resamples=config.resamples,
            rng=rng,
        )
    else:
        bootstrap_values = _generic_bootstrap_values(
            y_true,
            predictions,
            task_type=task_type,
            metric_names=metric_names,
            resamples=config.resamples,
            rng=rng,
        )

    intervals = {
        name: _interval_entry(
            estimate=float(point_metrics[name]),
            values=bootstrap_values[name],
            confidence_level=config.confidence_level,
            requested_resamples=config.resamples,
        )
        for name in metric_names
    }
    overall_status = "evaluated" if any(entry["status"] == "evaluated" for entry in intervals.values()) else "unavailable"
    return {**metadata, "status": overall_status, "metrics": intervals}
