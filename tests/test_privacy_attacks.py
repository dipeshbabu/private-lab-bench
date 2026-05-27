import numpy as np

from privatelabbench.privacy.attacks import membership_inference_risk
from privatelabbench.privacy.policy import PrivacyRiskPolicy, evaluate_privacy_gate


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


def test_privacy_risk_gate_blocks_excessive_attack_signal():
    gate = evaluate_privacy_gate(
        {
            "risk_level": "high",
            "member_advantage": 0.42,
            "attack_auc": 0.91,
        },
        PrivacyRiskPolicy(max_level="moderate", max_member_advantage=0.35, max_attack_auc=0.85),
    )

    assert gate["status"] == "fail"
    assert gate["publishable"] is False
    assert "risk_level_exceeds_policy" in gate["violations"]
    assert "member_advantage_exceeds_policy" in gate["violations"]
    assert "attack_auc_exceeds_policy" in gate["violations"]


def test_privacy_risk_gate_can_require_attack_evidence():
    gate = evaluate_privacy_gate(None, PrivacyRiskPolicy(require_attack=True))

    assert gate["status"] == "fail"
    assert gate["publishable"] is False
    assert gate["violations"] == ["privacy_attack_required"]
