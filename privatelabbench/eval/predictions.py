from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from privatelabbench.eval.metrics import classification_metrics, regression_metrics
from privatelabbench.privacy.attacks import membership_inference_risk
from privatelabbench.tasks.molecules import infer_task_type


@dataclass(frozen=True)
class PredictionEvaluation:
    dataset_path: str
    target_column: str
    prediction_column: str
    task_type: str
    n_samples: int
    metrics: dict[str, float]
    prediction_summary: dict[str, float]
    split_column: str | None = None
    privacy_risk: dict[str, float | str] | None = None


def _summary(values: np.ndarray, prefix: str) -> dict[str, float]:
    return {
        f"{prefix}_mean": float(np.mean(values)),
        f"{prefix}_std": float(np.std(values)),
        f"{prefix}_min": float(np.min(values)),
        f"{prefix}_max": float(np.max(values)),
    }


def _normalize_split_value(value: Any) -> str:
    normalized = str(value).strip().lower()
    if normalized in {"train", "training", "member", "members", "in", "1", "true"}:
        return "train"
    if normalized in {"test", "holdout", "validation", "val", "nonmember", "nonmembers", "out", "0", "false"}:
        return "test"
    raise ValueError(
        "split_column values must identify train/member rows and test/nonmember rows. "
        f"Unsupported value: {value!r}"
    )


def evaluate_prediction_csv(
    path: str,
    *,
    target: str,
    prediction_column: str,
    task_type: str | None = None,
    split_column: str | None = None,
) -> PredictionEvaluation:
    df = pd.read_csv(path)
    required = {target, prediction_column}
    if split_column:
        required.add(split_column)
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required column(s): {', '.join(sorted(missing))}")

    selected_columns = [target, prediction_column]
    if split_column:
        selected_columns.append(split_column)
    df = df[selected_columns].dropna()
    if df.empty:
        raise ValueError("No valid rows found after dropping missing targets or predictions.")

    y_true = df[target].astype(float).to_numpy()
    y_pred = df[prediction_column].astype(float).to_numpy()
    inferred = task_type or infer_task_type(y_true)
    if inferred not in {"regression", "classification"}:
        raise ValueError("task_type must be 'regression' or 'classification'")

    if inferred == "classification":
        metrics = classification_metrics(y_true.astype(int), y_pred)
    else:
        metrics = regression_metrics(y_true, y_pred)

    prediction_summary = {}
    prediction_summary.update(_summary(y_true, "target"))
    prediction_summary.update(_summary(y_pred, "prediction"))
    prediction_summary["mean_absolute_prediction_error"] = float(np.mean(np.abs(y_true - y_pred)))

    privacy_risk = None
    if split_column:
        split = df[split_column].map(_normalize_split_value).to_numpy()
        train_mask = split == "train"
        test_mask = split == "test"
        privacy_risk = membership_inference_risk(
            train_y=y_true[train_mask],
            train_score=y_pred[train_mask],
            test_y=y_true[test_mask],
            test_score=y_pred[test_mask],
            task_type=inferred,
        )
        privacy_risk["split_column"] = split_column

    return PredictionEvaluation(
        dataset_path=path,
        target_column=target,
        prediction_column=prediction_column,
        task_type=inferred,
        n_samples=int(len(df)),
        metrics=metrics,
        prediction_summary=prediction_summary,
        split_column=split_column,
        privacy_risk=privacy_risk,
    )
