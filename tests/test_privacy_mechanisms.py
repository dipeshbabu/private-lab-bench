import warnings

import numpy as np
import pytest

from privatelabbench.privacy.dp import PrivacyConfig, privacy_summary, release_metrics
from privatelabbench.privacy.formal import (
    BoundedMeanQuery,
    PrivacyBudget,
    release_bounded_mean,
    release_bounded_means,
)


def test_metric_perturbation_is_labeled_non_formal_and_reproducible():
    config = PrivacyConfig(mode="metric_perturbation", epsilon=4.0, sensitivity=0.5, seed=7)
    first = release_metrics({"mae": 0.2, "rmse": 0.3}, config)
    second = release_metrics({"mae": 0.2, "rmse": 0.3}, config)

    assert first.metrics == second.metrics
    assert first.metadata["mechanism"] == "metric_perturbation"
    assert first.metadata["guarantee_level"] == "heuristic_no_dp_guarantee"
    assert first.metadata["formal_dp"] is False
    assert first.metadata["noise_scale"] == pytest.approx(0.125)
    assert "not a formal differential-privacy guarantee" in privacy_summary(config)


def test_legacy_dp_alias_warns_and_normalizes_to_metric_perturbation():
    config = PrivacyConfig(mode="dp", epsilon=8.0, sensitivity=1.0, seed=13)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        metadata = config.report_metadata()
    assert any("deprecated" in str(item.message) for item in caught)
    assert metadata["configured_mode"] == "dp"
    assert metadata["mode"] == "metric_perturbation"
    assert metadata["legacy_dp_alias"] is True
    assert metadata["formal_dp"] is False


def test_privacy_config_rejects_fake_formal_mode():
    with pytest.raises(ValueError, match="metric_perturbation"):
        PrivacyConfig(mode="formal_dp").validate()


@pytest.mark.parametrize(
    "epsilon,sensitivity",
    [(0.0, 1.0), (-1.0, 1.0), (1.0, 0.0), (1.0, -1.0)],
)
def test_metric_release_rejects_invalid_noise_parameters(epsilon, sensitivity):
    with pytest.raises(ValueError):
        release_metrics({"mae": 0.2}, PrivacyConfig(mode="metric_perturbation", epsilon=epsilon, sensitivity=sensitivity))


def test_bounded_mean_clips_and_computes_replace_one_sensitivity():
    query = BoundedMeanQuery(name="score", values=[-5.0, 0.0, 5.0, 50.0], lower=0.0, upper=10.0)
    assert query.n == 4
    assert query.clipped_mean() == pytest.approx(3.75)
    assert query.sensitivity == pytest.approx(2.5)


def test_bounded_mean_release_records_formal_query_contract():
    query = BoundedMeanQuery(name="bounded-score", values=[0.0, 1.0, 2.0, 3.0], lower=0.0, upper=4.0)
    release = release_bounded_mean(query, epsilon=2.0, seed=11)

    assert release.adjacency == "fixed_size_replace_one"
    assert release.guarantee == "pure_epsilon_dp_mathematical_model"
    assert release.sensitivity == pytest.approx(1.0)
    assert release.noise_scale == pytest.approx(0.5)
    assert release.epsilon == 2.0
    assert release.delta == 0.0


def test_bounded_mean_release_is_reproducible_given_seed():
    query = BoundedMeanQuery(name="bounded-score", values=[1.0, 2.0, 3.0], lower=0.0, upper=4.0)
    a = release_bounded_mean(query, epsilon=1.0, seed=42)
    b = release_bounded_mean(query, epsilon=1.0, seed=42)
    assert a.value == b.value


def test_privacy_budget_enforces_sequential_composition():
    budget = PrivacyBudget(epsilon_limit=1.0)
    budget.spend(label="a", epsilon=0.4)
    budget.spend(label="b", epsilon=0.6)
    assert budget.epsilon_spent == pytest.approx(1.0)
    assert budget.epsilon_remaining == pytest.approx(0.0)
    with pytest.raises(ValueError, match="budget exceeded"):
        budget.spend(label="c", epsilon=0.01)


def test_multiple_bounded_means_split_and_account_total_budget():
    result = release_bounded_means(
        [
            BoundedMeanQuery("a", [0.0, 1.0, 2.0], 0.0, 2.0),
            BoundedMeanQuery("b", [10.0, 11.0, 12.0], 10.0, 12.0),
        ],
        epsilon_total=1.0,
        seed=5,
    )
    assert result["budget"]["epsilon_spent"] == pytest.approx(1.0)
    assert [spend["epsilon"] for spend in result["budget"]["spends"]] == pytest.approx([0.5, 0.5])
    assert all(release["epsilon"] == pytest.approx(0.5) for release in result["releases"])


def test_weighted_bounded_mean_composition_uses_declared_total_budget():
    result = release_bounded_means(
        [
            BoundedMeanQuery("a", [0.0, 1.0], 0.0, 1.0),
            BoundedMeanQuery("b", [0.0, 1.0], 0.0, 1.0),
        ],
        epsilon_total=2.0,
        weights=[1.0, 3.0],
        seed=2,
    )
    spends = result["budget"]["spends"]
    assert spends[0]["epsilon"] == pytest.approx(0.5)
    assert spends[1]["epsilon"] == pytest.approx(1.5)


def test_bounded_query_rejects_invalid_bounds_or_values():
    with pytest.raises(ValueError, match="lower bound"):
        BoundedMeanQuery("x", [1.0], 1.0, 1.0).validate()
    with pytest.raises(ValueError, match="finite"):
        BoundedMeanQuery("x", [1.0, np.nan], 0.0, 2.0).validate()
    with pytest.raises(ValueError, match="at least one"):
        BoundedMeanQuery("x", [], 0.0, 1.0).validate()
