from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(math.sqrt(mean_squared_error(y_true, y_pred))),
        "r2": float(r2_score(y_true, y_pred)),
    }


def classification_metrics(y_true: np.ndarray, y_score: np.ndarray) -> dict[str, float]:
    y_label = (y_score >= 0.5).astype(int)
    out: dict[str, float] = {
        "accuracy": float(accuracy_score(y_true, y_label)),
        "f1": float(f1_score(y_true, y_label, zero_division=0)),
    }
    try:
        out["auroc"] = float(roc_auc_score(y_true, y_score))
    except ValueError:
        out["auroc"] = float("nan")
    return out


def multiclass_metrics(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    *,
    labels: Sequence[int] | None = None,
) -> dict[str, float]:
    if probabilities.ndim != 2 or probabilities.shape[1] < 2:
        raise ValueError("multiclass probabilities must be a 2D array with at least two class columns")
    predicted = np.argmax(probabilities, axis=1)
    label_values = list(labels) if labels is not None else list(range(probabilities.shape[1]))
    out: dict[str, float] = {
        "accuracy": float(accuracy_score(y_true, predicted)),
        "macro_f1": float(f1_score(y_true, predicted, labels=label_values, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y_true, predicted, labels=label_values, average="weighted", zero_division=0)),
        "log_loss": float(log_loss(y_true, probabilities, labels=label_values)),
    }
    try:
        out["macro_auroc_ovr"] = float(
            roc_auc_score(y_true, probabilities, labels=label_values, multi_class="ovr", average="macro")
        )
    except ValueError:
        out["macro_auroc_ovr"] = float("nan")
    return out


def summarize_metrics(metrics: dict[str, Any]) -> str:
    parts = []
    for key, value in metrics.items():
        if isinstance(value, float):
            parts.append(f"{key}: {value:.4f}" if math.isfinite(value) else f"{key}: nan")
        else:
            parts.append(f"{key}: {value}")
    return ", ".join(parts)
