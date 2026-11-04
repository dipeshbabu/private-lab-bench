from __future__ import annotations

from typing import Literal

import numpy as np
from sklearn.metrics import roc_auc_score

from privatelabbench.privacy.attack_registry import (
    has_privacy_attack,
    register_privacy_attack,
)

RiskLevel = Literal["low", "moderate", "high"]
LOSS_THRESHOLD_ATTACK_ID = "loss-threshold-membership-inference"


def _prediction_loss(
    y_true: np.ndarray, y_score: np.ndarray, task_type: str
) -> np.ndarray:
    y_true, y_score = np.asarray(y_true, dtype=float), np.asarray(y_score, dtype=float)
    if (
        y_true.ndim != 1
        or y_score.shape != y_true.shape
        or not len(y_true)
        or not np.isfinite(y_true).all()
        or not np.isfinite(y_score).all()
    ):
        raise ValueError(
            "Membership audits require aligned, nonempty, finite 1D targets and scores"
        )
    if task_type == "classification":
        if (
            not np.isin(y_true, [0, 1]).all()
            or not ((0 <= y_score) & (y_score <= 1)).all()
        ):
            raise ValueError(
                "Classification audits require binary targets and probabilities in [0, 1]"
            )
        clipped = np.clip(y_score.astype(float), 1e-6, 1.0 - 1e-6)
        labels = y_true.astype(int)
        return -(labels * np.log(clipped) + (1 - labels) * np.log(1.0 - clipped))
    with np.errstate(over="ignore"):
        losses = np.abs(y_true - y_score)
    if not np.isfinite(losses).all():
        raise ValueError("Prediction losses must be finite")
    return losses


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
) -> dict[str, float | str | bool]:
    """Baseline empirical membership-inference audit from train/test prediction loss.

    This is an attack diagnostic, not a privacy guarantee. A low measured attack
    signal does not imply differential privacy or prove absence of leakage.
    """
    if task_type not in {"regression", "classification"}:
        raise ValueError("task_type must be 'regression' or 'classification'")
    member_loss = _prediction_loss(train_y, train_score, task_type)
    nonmember_loss = _prediction_loss(test_y, test_score, task_type)
    losses = np.concatenate([member_loss, nonmember_loss])
    labels = np.concatenate(
        [np.ones(len(member_loss), dtype=int), np.zeros(len(nonmember_loss), dtype=int)]
    )

    # Evaluate whole tie groups with cumulative counts: O(n log n), rather
    # than scanning all n rows at each of n distinct thresholds. Equal weight
    # for the two membership classes prevents sample imbalance looking like leakage.
    order = np.argsort(losses, kind="stable")
    sorted_losses = losses[order]
    ends = np.flatnonzero(np.r_[sorted_losses[1:] != sorted_losses[:-1], True])
    member_count = np.cumsum(labels[order])[ends]
    nonmember_count = ends + 1 - member_count
    lower_accuracy = 0.5 * (
        member_count / len(member_loss) + 1 - nonmember_count / len(nonmember_loss)
    )
    accuracies = np.stack([lower_accuracy, 1 - lower_accuracy])
    direction, candidate = np.unravel_index(np.argmax(accuracies), accuracies.shape)
    best_accuracy = float(accuracies[direction, candidate])
    best_threshold = float(sorted_losses[ends[candidate]])
    directional_auc = float(roc_auc_score(labels, -losses))
    auc = max(directional_auc, 1.0 - directional_auc)

    advantage = max(0.0, (best_accuracy - 0.5) * 2.0)
    train_loss_mean = float(np.sum(member_loss / len(member_loss)))
    test_loss_mean = float(np.sum(nonmember_loss / len(nonmember_loss)))
    loss_gap = float(test_loss_mean - train_loss_mean)

    auc_for_level = max(0.0, (auc - 0.5) * 2.0)
    level = _risk_level(max(advantage, auc_for_level))

    return {
        # Keep the historical machine-readable identifier for report compatibility.
        "attack": "loss_threshold_membership_inference",
        "registry_id": LOSS_THRESHOLD_ATTACK_ID,
        "baseline": True,
        "evidence_level": "empirical_audit",
        "guarantee": "none",
        "risk_level": level,
        "member_advantage": float(advantage),
        "attack_auc": auc,
        "directional_attack_auc": directional_auc,
        "threshold_attack_accuracy": best_accuracy,
        "threshold_accuracy_basis": "balanced_membership_classes",
        "loss_threshold_direction": "loss_gt" if direction else "loss_le",
        "loss_threshold": best_threshold,
        "train_loss_mean": train_loss_mean,
        "test_loss_mean": test_loss_mean,
        "loss_gap": loss_gap,
        "n_member": int(len(member_loss)),
        "n_nonmember": int(len(nonmember_loss)),
    }


def ensure_builtin_privacy_attacks_registered() -> None:
    if not has_privacy_attack(LOSS_THRESHOLD_ATTACK_ID):
        register_privacy_attack(
            LOSS_THRESHOLD_ATTACK_ID,
            membership_inference_risk,
            description="Simple loss-threshold membership-inference baseline for regression and binary classification.",
            evidence_level="empirical_audit",
            baseline=True,
        )
