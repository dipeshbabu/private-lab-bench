from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)

METRIC_DIRECTIONS = {
    "mae": "lower_is_better",
    "rmse": "lower_is_better",
    "log_loss": "lower_is_better",
    "r2": "higher_is_better",
    "accuracy": "higher_is_better",
    "f1": "higher_is_better",
    "auroc": "higher_is_better",
    "macro_f1": "higher_is_better",
    "weighted_f1": "higher_is_better",
    "macro_auroc_ovr": "higher_is_better",
    "spearman": "higher_is_better",
}

DEFAULT_METRICS = {
    "regression": ("mae", "rmse", "r2"),
    "classification": ("accuracy", "f1", "auroc"),
    "multiclass": (
        "accuracy",
        "macro_f1",
        "weighted_f1",
        "log_loss",
        "macro_auroc_ovr",
    ),
}


def selected_metrics(
    task_type: str, names: Sequence[str] | None = None
) -> tuple[str, ...]:
    if task_type not in DEFAULT_METRICS:
        raise ValueError("Unsupported metric task type")
    if names is not None and (
        not isinstance(names, (list, tuple))
        or any(not isinstance(name, str) for name in names)
    ):
        raise ValueError("Metric selection must be an explicit list of names")
    chosen = tuple(DEFAULT_METRICS[task_type] if names is None else names)
    allowed = set(DEFAULT_METRICS[task_type]) | (
        {"spearman"} if task_type == "regression" else set()
    )
    if not chosen or len(set(chosen)) != len(chosen) or not set(chosen) <= allowed:
        raise ValueError("Select unique metrics supported by the declared task type")
    return chosen


def spearman_correlation(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Average tied ranks, matching scipy.stats.spearmanr; no row omission."""
    y, p = np.asarray(y_true, dtype=float), np.asarray(y_pred, dtype=float)
    if (
        y.ndim != 1
        or p.shape != y.shape
        or not np.isfinite(y).all()
        or not np.isfinite(p).all()
    ):
        raise ValueError("Spearman requires aligned, finite one-dimensional scores")
    if len(y) < 2:
        return float("nan")
    a, b = (
        pd.Series(values).rank(method="average").to_numpy(dtype=float)
        for values in (y, p)
    )
    a = a - a.mean()
    b = b - b.mean()
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return (
        float(np.clip(np.dot(a, b) / denominator, -1.0, 1.0))
        if denominator
        else float("nan")
    )


def regression_metrics(
    y_true: np.ndarray, y_pred: np.ndarray, *, metric_names: Sequence[str] | None = None
) -> dict[str, float]:
    functions = {
        "mae": mean_absolute_error,
        "rmse": lambda y, p: math.sqrt(mean_squared_error(y, p)),
        "r2": r2_score,
        "spearman": spearman_correlation,
    }
    return {
        name: float(functions[name](y_true, y_pred))
        for name in selected_metrics("regression", metric_names)
    }


def classification_metrics(
    y_true: np.ndarray,
    y_score: np.ndarray,
    *,
    metric_names: Sequence[str] | None = None,
) -> dict[str, float]:
    names = selected_metrics("classification", metric_names)
    out: dict[str, float] = {}
    if set(names) & {"accuracy", "f1"}:
        y_label = (y_score >= 0.5).astype(int)
    if "accuracy" in names:
        out["accuracy"] = float(accuracy_score(y_true, y_label))
    if "f1" in names:
        out["f1"] = float(f1_score(y_true, y_label, zero_division=0))
    if "auroc" in names:
        try:
            out["auroc"] = float(roc_auc_score(y_true, y_score))
        except ValueError:
            out["auroc"] = float("nan")
    return {name: out[name] for name in names}


def multiclass_metrics(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    *,
    labels: Sequence[int] | None = None,
    metric_names: Sequence[str] | None = None,
) -> dict[str, float]:
    if probabilities.ndim != 2 or probabilities.shape[1] < 2:
        raise ValueError(
            "multiclass probabilities must be a 2D array with at least two class columns"
        )
    names = selected_metrics("multiclass", metric_names)
    if set(names) & {"accuracy", "macro_f1", "weighted_f1"}:
        predicted = np.argmax(probabilities, axis=1)
    label_values = (
        list(labels) if labels is not None else list(range(probabilities.shape[1]))
    )
    out: dict[str, float] = {}
    if "accuracy" in names:
        out["accuracy"] = float(accuracy_score(y_true, predicted))
    if "macro_f1" in names:
        out["macro_f1"] = float(
            f1_score(
                y_true, predicted, labels=label_values, average="macro", zero_division=0
            )
        )
    if "weighted_f1" in names:
        out["weighted_f1"] = float(
            f1_score(
                y_true,
                predicted,
                labels=label_values,
                average="weighted",
                zero_division=0,
            )
        )
    if "log_loss" in names:
        out["log_loss"] = float(log_loss(y_true, probabilities, labels=label_values))
    if "macro_auroc_ovr" in names:
        try:
            out["macro_auroc_ovr"] = float(
                roc_auc_score(
                    y_true,
                    probabilities,
                    labels=label_values,
                    multi_class="ovr",
                    average="macro",
                )
            )
        except ValueError:
            out["macro_auroc_ovr"] = float("nan")
    return {name: out[name] for name in names}


def summarize_metrics(metrics: dict[str, Any]) -> str:
    parts = []
    for key, value in metrics.items():
        if isinstance(value, float):
            parts.append(
                f"{key}: {value:.4f}" if math.isfinite(value) else f"{key}: nan"
            )
        else:
            parts.append(f"{key}: {value}")
    return ", ".join(parts)
