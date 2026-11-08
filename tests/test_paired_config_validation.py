from dataclasses import replace

import pytest

from privatelabbench.eval.paired_comparison import PairedComparisonConfig


@pytest.mark.parametrize(
    "field", ["confidence_level", "practical_threshold", "noninferiority_margin"]
)
@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), -float("inf"), True, "0.1"]
)
def test_nonfinite_or_non_numeric_thresholds_cannot_produce_a_comparison_decision(
    field, value
):
    with pytest.raises(ValueError, match="finite"):
        replace(PairedComparisonConfig(), **{field: value}).validate()


@pytest.mark.parametrize(
    "field", ["resamples", "permutations", "seed", "min_samples", "min_slice_size"]
)
@pytest.mark.parametrize("value", [True, 100.5])
def test_fractional_or_boolean_counts_are_not_silently_interpreted_as_sampling_settings(
    field, value
):
    with pytest.raises(ValueError, match="integer"):
        replace(PairedComparisonConfig(), **{field: value}).validate()


@pytest.mark.parametrize(
    "changes",
    [
        {"seed": -1},
        {"resamples": 99},
        {"permutations": 1},
        {"min_samples": 1},
        {"min_slice_size": 0},
        {"practical_threshold": -1.0},
        {"noninferiority_margin": -1.0},
        {"include_slice_uncertainty": "yes"},
        {"metric": ""},
        {"metric": "unknown"},
    ],
)
def test_invalid_sampling_and_decision_boundaries_fail_before_evaluation(changes):
    with pytest.raises(ValueError):
        replace(PairedComparisonConfig(), **changes).validate()


def test_boundary_settings_and_disabled_optional_tests_remain_valid():
    PairedComparisonConfig(
        resamples=100,
        permutations=0,
        min_samples=2,
        min_slice_size=1,
        seed=0,
        practical_threshold=0,
        noninferiority_margin=0,
    ).validate()
