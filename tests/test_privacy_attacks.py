import numpy as np

from privatelabbench.privacy.attacks import membership_inference_risk


def test_membership_inference_risk_detects_train_test_loss_gap():
    risk = membership_inference_risk(
        train_y=np.array([0.0, 1.0, 0.0, 1.0]),
        train_score=np.array([0.01, 0.99, 0.02, 0.98]),
        test_y=np.array([0.0, 1.0, 0.0, 1.0]),
        test_score=np.array([0.45, 0.55, 0.51, 0.49]),
        task_type="classification",
    )

    assert risk["attack"] == "loss_threshold_membership_inference"
    assert risk["member_advantage"] > 0
    assert risk["attack_auc"] > 0.5
    assert risk["risk_level"] in {"moderate", "high"}
