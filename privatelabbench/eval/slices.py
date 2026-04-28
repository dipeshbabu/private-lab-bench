from __future__ import annotations

import numpy as np


def regression_error_slices(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    if len(y_true) == 0:
        return {}
    err = y_pred - y_true
    abs_err = np.abs(err)
    high_cut = float(np.quantile(y_true, 0.75))
    low_cut = float(np.quantile(y_true, 0.25))
    large_cut = float(np.quantile(abs_err, 0.90))
    high_mask = y_true >= high_cut
    low_mask = y_true <= low_cut
    large_mask = abs_err >= large_cut
    return {
        "mean_absolute_error_high_label_range": float(np.mean(abs_err[high_mask])) if np.any(high_mask) else 0.0,
        "mean_absolute_error_low_label_range": float(np.mean(abs_err[low_mask])) if np.any(low_mask) else 0.0,
        "large_absolute_error_threshold_p90": large_cut,
        "large_absolute_error_fraction": float(np.mean(large_mask)),
        "prediction_bias_mean_error": float(np.mean(err)),
        "prediction_bias_median_error": float(np.median(err)),
        "outlier_prediction_fraction_p99": float(np.mean(np.abs(y_pred - np.mean(y_pred)) >= 3.0 * (np.std(y_pred) or 1.0))),
    }


def classification_error_slices(y_true: np.ndarray, y_score: np.ndarray) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=int)
    y_score = np.asarray(y_score, dtype=float)
    if len(y_true) == 0:
        return {}
    pred = (y_score >= 0.5).astype(int)
    incorrect = pred != y_true
    positive = y_true == 1
    negative = y_true == 0
    high_conf = np.maximum(y_score, 1.0 - y_score) >= 0.8
    return {
        "error_rate": float(np.mean(incorrect)),
        "positive_class_error_rate": float(np.mean(incorrect[positive])) if np.any(positive) else 0.0,
        "negative_class_error_rate": float(np.mean(incorrect[negative])) if np.any(negative) else 0.0,
        "high_confidence_error_fraction": float(np.mean(incorrect & high_conf)),
        "mean_score_positive_class": float(np.mean(y_score[positive])) if np.any(positive) else 0.0,
        "mean_score_negative_class": float(np.mean(y_score[negative])) if np.any(negative) else 0.0,
        "prediction_bias_mean_score_minus_label": float(np.mean(y_score - y_true)),
    }
