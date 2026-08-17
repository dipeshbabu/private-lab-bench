import numpy as np
import pytest

from privatelabbench.privacy.attack_registry import (
    clear_privacy_attacks_for_testing,
    get_privacy_attack,
    list_privacy_attacks,
    register_privacy_attack,
)
from privatelabbench.privacy.attacks import (
    LOSS_THRESHOLD_ATTACK_ID,
    ensure_builtin_privacy_attacks_registered,
    membership_inference_risk,
)
from privatelabbench.privacy.policy import PrivacyRiskPolicy, evaluate_privacy_gate


def setup_function():
    clear_privacy_attacks_for_testing()


def teardown_function():
    clear_privacy_attacks_for_testing()
    ensure_builtin_privacy_attacks_registered()


def test_membership_inference_risk_detects_train_test_loss_gap():
    risk = membership_inference_risk(
        train_y=np.array([0.0, 1.0, 0.0, 1.0]),
        train_score=np.array([0.01, 0.99, 0.02, 0.98]),
        test_y=np.array([0.0, 1.0, 0.0, 1.0]),
        test_score=np.array([0.45, 0.55, 0.51, 0.49]),
        task_type="classification",
    )

    assert risk["attack"] == "loss_threshold_membership_inference"
    assert risk["registry_id"] == LOSS_THRESHOLD_ATTACK_ID
    assert risk["baseline"] is True
    assert risk["evidence_level"] == "empirical_audit"
    assert risk["guarantee"] == "none"
    assert risk["member_advantage"] > 0
    assert risk["attack_auc"] > 0.5
    assert risk["risk_level"] in {"moderate", "high"}


def test_builtin_membership_attack_is_registered_as_baseline():
    ensure_builtin_privacy_attacks_registered()
    spec = get_privacy_attack(LOSS_THRESHOLD_ATTACK_ID)
    assert spec.runner is membership_inference_risk
    assert spec.baseline is True
    assert spec.evidence_level == "empirical_audit"
    assert len(list_privacy_attacks()) == 1


def test_privacy_attack_registry_supports_community_attacks_and_rejects_duplicates():
    def dummy_attack(**kwargs):
        return {"status": "ok"}

    register_privacy_attack("dummy", dummy_attack, description="community test")
    assert get_privacy_attack("dummy").description == "community test"
    with pytest.raises(ValueError, match="already registered"):
        register_privacy_attack("dummy", dummy_attack)


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
