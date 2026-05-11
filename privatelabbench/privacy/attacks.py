from __future__ import annotations

import math
from typing import Literal

import numpy as np
from sklearn.metrics import roc_auc_score


RiskLevel = Literal["low", "moderate", "high"]


def _prediction_loss(y_true: np.ndarray, y_score: np.ndarray, task_type: str) -> np.ndarray:
    if task_type == "classification":
        clipped = np.clip(y_score.astype(float), 1e-6, 1.0 - 1e-6)
        labels = y_true.astype(int)
        return -(labels * np.log(clipped) + (1 - labels) * np.log(1.0 - clipped))
    return np.abs(y_true.astype(float) - y_score.astype(float))


def _risk_level(advantage: float) -> RiskLevel:
    if advantage >= 0.35:
        return "high"
    if advantage >= 0.15:
        return "moderate"
    return "low"


def membership_inference_risk(
    *,
    train_y: np.ndarray,
    train_score: np.ndarray,
    test_y: np.ndarray,
    test_score: np.ndarray,
    task_type: str,
) -> dict[str, float | str]:
    """Estimate aggregate membership-inference risk from train/test prediction loss.

    The attack is intentionally simple and local: samples with unusually low loss are
    treated as likely members. Only aggregate risk metrics are returned.
    """
    if task_type not in {"regression", "classification"}:
        raise ValueError("task_type must be 'regression' or 'classification'")
    if len(train_y) == 0 or len(test_y) == 0:
        raise ValueError("train and test sets must both contain at least one sample")

    member_loss = _prediction_loss(train_y, train_score, task_type)
    nonmember_loss = _prediction_loss(test_y, test_score, task_type)
    losses = np.concatenate([member_loss, nonmember_loss])
    labels = np.concatenate([np.ones(len(member_loss), dtype=int), np.zeros(len(nonmember_loss), dtype=int)])

    candidates = np.unique(losses)
    best_accuracy = 0.5
    best_threshold = float(np.median(losses))
    for threshold in candidates:
        predictions = (losses <= threshold).astype(int)
        accuracy = float(np.mean(predictions == labels))
        if accuracy > best_accuracy:
            best_accuracy = accuracy
            best_threshold = float(threshold)

    try:
        auc = float(roc_auc_score(labels, -losses))
    except ValueError:
        auc = float("nan")

    advantage = max(0.0, (best_accuracy - 0.5) * 2.0)
    train_loss_mean = float(np.mean(member_loss))
    test_loss_mean = float(np.mean(nonmember_loss))
    loss_gap = float(test_loss_mean - train_loss_mean)

    if math.isnan(auc):
        auc_for_level = advantage
    else:
        auc_for_level = max(0.0, (auc - 0.5) * 2.0)
    level = _risk_level(max(advantage, auc_for_level))

    return {
        "attack": "loss_threshold_membership_inference",
        "risk_level": level,
        "member_advantage": float(advantage),
        "attack_auc": auc,
        "threshold_attack_accuracy": best_accuracy,
        "loss_threshold": best_threshold,
        "train_loss_mean": train_loss_mean,
        "test_loss_mean": test_loss_mean,
        "loss_gap": loss_gap,
        "n_member": int(len(member_loss)),
        "n_nonmember": int(len(nonmember_loss)),
    }
