import numpy as np
import pytest

from privatelabbench.privacy.attacks import membership_inference_risk
from privatelabbench.privacy.dp import PrivacyConfig, release_metrics
from privatelabbench.privacy.policy import PrivacyRiskPolicy
from privatelabbench.privacy.release import (
    AggregateReleasePolicy,
    evaluate_aggregate_release,
)


@pytest.mark.parametrize(
    "field", ["min_clients", "min_total_samples", "min_client_samples"]
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 1.5, True])
def test_aggregate_policy_cannot_silently_weaken_thresholds(field, value):
    with pytest.raises(ValueError):
        AggregateReleasePolicy.from_config({field: value})
    with pytest.raises(ValueError):
        AggregateReleasePolicy(**{field: value})


def test_aggregate_gate_rejects_inconsistent_counts():
    with pytest.raises(ValueError):
        evaluate_aggregate_release(
            n_clients=3, total_samples=100, client_sample_counts=[]
        )


@pytest.mark.parametrize(
    "settings",
    [
        {"epsilon": True},
        {"sensitivity": True},
        {"seed": 1.5},
        {"risk_policy": {"max_attack_auc": float("nan")}},
        {"aggregate_policy": {"min_clients": 1.5}},
    ],
)
def test_config_validation_and_execution_reject_invalid_privacy_settings(
    tmp_path, settings
):
    import yaml

    from privatelabbench.runner import run_config
    from privatelabbench.validation import validate_config

    source = tmp_path / "data.csv"
    source.write_text("target,prediction\n1,1.1\n2,1.9\n", encoding="utf-8")
    config = tmp_path / "evaluation.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "task": "predictions",
                "input": {
                    "path": str(source),
                    "target_column": "target",
                    "prediction_column": "prediction",
                    "task_type": "regression",
                },
                "privacy": settings,
            }
        ),
        encoding="utf-8",
    )
    result = validate_config(str(config))
    assert not result.valid
    assert any("privacy" in error.lower() for error in result.errors)
    with pytest.raises(ValueError):
        run_config(str(config))


@pytest.mark.parametrize("field", ["max_member_advantage", "max_attack_auc"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1, True])
def test_risk_thresholds_cannot_disable_a_release_gate(field, value):
    with pytest.raises(ValueError):
        PrivacyRiskPolicy.from_config({field: value})
    with pytest.raises(ValueError):
        PrivacyRiskPolicy(**{field: value})


@pytest.mark.parametrize(
    "settings",
    [
        {"max_attack_aucc": 0.1},
        {"require_attack": "false"},
        {"require_attack": 0},
        {"max_level": "unknown"},
        ["invalid"],
    ],
)
def test_invalid_risk_policies_fail_closed(settings):
    with pytest.raises(ValueError):
        PrivacyRiskPolicy.from_config(settings)


@pytest.mark.parametrize("field", ["epsilon", "sensitivity"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_nonfinite_or_boolean_metric_noise_parameters_are_rejected(field, value):
    with pytest.raises(ValueError):
        PrivacyConfig(mode="metric_perturbation", **{field: value}).validate()


def audit(member, nonmember):
    return membership_inference_risk(
        train_y=np.zeros(len(member)),
        train_score=np.asarray(member),
        test_y=np.zeros(len(nonmember)),
        test_score=np.asarray(nonmember),
        task_type="regression",
    )


@pytest.mark.parametrize("sizes", [(90, 10), (10, 90)])
def test_membership_risk_does_not_confuse_population_imbalance_with_leakage(sizes):
    result = audit(np.ones(sizes[0]), np.ones(sizes[1]))
    assert result["member_advantage"] == 0.0
    assert result["threshold_attack_accuracy"] == 0.5
    assert result["attack_auc"] == 0.5
    assert result["risk_level"] == "low"


def test_inverted_loss_separation_is_still_a_perfect_membership_attack():
    result = audit([5.0] * 20, [1.0] * 20)
    assert result["member_advantage"] == 1.0
    assert result["attack_auc"] == 1.0
    assert result["risk_level"] == "high"


@pytest.mark.parametrize(
    "bad", [np.array([1.0]), np.array([np.nan, 1.0]), np.array([[1.0], [2.0]])]
)
def test_membership_audit_rejects_misaligned_or_nonfinite_arrays(bad):
    with pytest.raises(ValueError):
        membership_inference_risk(
            train_y=np.array([0.0, 1.0]),
            train_score=bad,
            test_y=np.array([0.0, 1.0]),
            test_score=np.array([0.2, 0.8]),
            task_type="classification",
        )


@pytest.mark.parametrize("seed", [True, -1, 1.5, "13"])
def test_invalid_noise_seed_is_rejected(seed):
    with pytest.raises(ValueError):
        PrivacyConfig(seed=seed).validate()


@pytest.mark.parametrize("epsilon,sensitivity", [(1e-300, 1e300), (1e300, 1e-300)])
def test_unrepresentable_noise_scale_is_rejected(epsilon, sensitivity):
    with pytest.raises(ValueError, match="noise scale"):
        PrivacyConfig(
            mode="metric_perturbation", epsilon=epsilon, sensitivity=sensitivity
        ).validate()


def test_noise_sampling_cannot_return_a_successful_infinite_release():
    with pytest.raises(ValueError, match="nonfinite release"):
        release_metrics(
            {"mae": np.finfo(float).max},
            PrivacyConfig(
                mode="metric_perturbation", epsilon=1.0, sensitivity=1e308, seed=13
            ),
        )


def test_threshold_search_matches_independent_balanced_accuracy_reference():
    from sklearn.metrics import balanced_accuracy_score, roc_auc_score

    rng = np.random.default_rng(140)
    for n_member, n_nonmember in [(3, 11), (11, 3), (20, 20)]:
        for _ in range(10):
            member = rng.integers(0, 6, n_member).astype(float)
            nonmember = rng.integers(0, 6, n_nonmember).astype(float)
            losses = np.r_[member, nonmember]
            labels = np.r_[np.ones(n_member), np.zeros(n_nonmember)]
            expected = max(
                balanced_accuracy_score(labels, predictions)
                for threshold in np.unique(losses)
                for predictions in [losses <= threshold, losses > threshold]
            )
            result = audit(member, nonmember)
            assert result["threshold_attack_accuracy"] == pytest.approx(expected)
            predictions = (
                losses > result["loss_threshold"]
                if result["loss_threshold_direction"] == "loss_gt"
                else losses <= result["loss_threshold"]
            )
            assert balanced_accuracy_score(labels, predictions) == pytest.approx(
                expected
            )
            raw_auc = roc_auc_score(labels, -losses)
            assert result["attack_auc"] == pytest.approx(max(raw_auc, 1 - raw_auc))


def test_threshold_audit_handles_large_distinct_loss_arrays():
    result = audit(np.arange(50000) / 50000, 2 + np.arange(50000) / 50000)
    assert result["member_advantage"] == result["attack_auc"] == 1.0


@pytest.mark.parametrize(
    "targets,scores",
    [([0, 2], [0.1, 0.9]), ([0, 1], [-0.1, 0.9]), ([0, 1], [0.1, 1.1])],
)
def test_classification_audit_rejects_invalid_targets_or_probabilities(targets, scores):
    with pytest.raises(ValueError):
        membership_inference_risk(
            train_y=targets,
            train_score=scores,
            test_y=[0, 1],
            test_score=[0.1, 0.9],
            task_type="classification",
        )
