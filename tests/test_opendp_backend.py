import json
import math
import sys

import pytest

from privatelabbench.privacy.formal import (
    BoundedMeanQuery,
    PrivacyBudget,
    release_bounded_means,
)
from privatelabbench.privacy.opendp_backend import OpenDPBoundedMean


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_budget_rejects_nonfinite_limits_and_spends(value):
    with pytest.raises(ValueError):
        PrivacyBudget(value)
    with pytest.raises(ValueError):
        PrivacyBudget(1.0, delta_limit=value)
    ledger = PrivacyBudget(1.0)
    with pytest.raises(ValueError):
        ledger.spend(label="query", epsilon=value)
    with pytest.raises(ValueError):
        ledger.spend(label="query", epsilon=0.1, delta=value)
    assert not ledger.spends


def test_budget_never_uses_absolute_slack_to_exceed_a_small_limit():
    ledger = PrivacyBudget(1e-15)
    with pytest.raises(ValueError, match="exceeded"):
        ledger.spend(label="query", epsilon=1e-13)
    ledger = PrivacyBudget(0.3)
    ledger.spend(label="a", epsilon=0.1)
    ledger.spend(label="b", epsilon=0.2)
    with pytest.raises(ValueError, match="exceeded"):
        ledger.spend(label="c", epsilon=1e-16)
    ledger = PrivacyBudget(1e100)
    ledger.spend(label="large", epsilon=1e100)
    with pytest.raises(ValueError, match="exceeded"):
        ledger.spend(label="tiny", epsilon=1e-100)


def test_reference_batch_rounds_allocations_down_instead_of_relaxing_budget():
    result = release_bounded_means(
        [BoundedMeanQuery(str(i), [0.0, 1.0], 0.0, 1.0) for i in range(11)],
        epsilon_total=1.0,
        seed=5,
    )
    assert result["budget"]["epsilon_spent"] <= 1.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"public_size": True},
        {"public_size": 0},
        {"public_size": 1.5},
        {"name": ""},
        {"lower": math.nan},
        {"upper": math.inf},
        {"lower": 1, "upper": 1},
        {"epsilon": 0},
        {"epsilon": math.nan},
        {"lower": -1e308, "upper": 1e308},
    ],
)
def test_query_policy_rejects_invalid_public_parameters(kwargs):
    settings = dict(
        name="public-measurement", lower=0.0, upper=1.0, public_size=3, epsilon=0.5
    )
    settings.update(kwargs)
    with pytest.raises(ValueError):
        OpenDPBoundedMean(**settings)


def test_missing_dependency_has_no_numpy_fallback(monkeypatch):
    monkeypatch.setitem(sys.modules, "opendp.prelude", None)
    query = OpenDPBoundedMean("query", 0.0, 1.0, 3, 0.5)
    ledger = PrivacyBudget(1.0)
    with pytest.raises(ValueError, match=r"\[opendp\]"):
        query.release([0.0, 0.5, 1.0], budget=ledger)
    assert not ledger.spends


def require_opendp():
    return pytest.importorskip("opendp.prelude")


@pytest.mark.parametrize(
    "lower,upper,n", [(0.0, 1.0, 3), (-10.0, 5.0, 11), (1.0, 2.0, 1)]
)
def test_actual_upstream_chain_certifies_replace_one_and_clips(lower, upper, n):
    dp = require_opendp()
    query = OpenDPBoundedMean("public-query", lower, upper, n, 0.5)
    measurement, sensitivity = query.measurement()
    assert measurement.check(2, 0.5)
    assert not measurement.check(2, 0.49)
    assert sensitivity >= (upper - lower) / n
    assert measurement.input_domain.member([float(lower)] * n)
    assert not measurement.input_domain.member([float(lower)] * (n + 1))
    assert math.isfinite(measurement([float(lower - 100)] * n))
    # Use OpenDP's own composition, independently of our budget ledger.
    composition = dp.c.make_composition([measurement, measurement])
    assert composition.check(2, 1.0)
    assert not composition.check(2, 0.99)


def test_release_charges_shared_budget_and_serializes_no_exact_values():
    require_opendp()
    query = OpenDPBoundedMean("public-query", 0.0, 1.0, 3, 0.5)
    ledger = PrivacyBudget(1.0)
    for values in ([0.0, 0.5, 1.0], [-100.0, 0.25, 999.0]):
        released = query.release(values, budget=ledger)
        payload = released.as_dict()
        assert math.isfinite(payload["value"])
        assert payload["adjacency"] == "fixed_size_replace_one"
        assert set(payload) == {
            "schema_version",
            "backend",
            "backend_version",
            "mechanism",
            "adjacency",
            "privacy_unit",
            "delta",
            "name",
            "value",
            "lower",
            "upper",
            "public_size",
            "epsilon",
            "sensitivity_bound",
        }
        json.dumps(payload, allow_nan=False)
    assert ledger.epsilon_spent == 1.0
    with pytest.raises(ValueError, match="budget exceeded"):
        query.release([0.0, 0.5, 1.0], budget=ledger)


@pytest.mark.parametrize(
    "values",
    [
        [1.0],
        [0.0, math.nan, 1.0],
        [0.0, math.inf, 1.0],
        [True, 0.0, 1.0],
        ["0", 0.5, 1.0],
    ],
)
def test_bad_private_inputs_are_local_rejections_without_spend(values):
    query = OpenDPBoundedMean("query", 0.0, 1.0, 3, 0.5)
    ledger = PrivacyBudget(1.0)
    with pytest.raises(ValueError):
        query.release(values, budget=ledger)
    assert not ledger.spends


@pytest.mark.parametrize(
    "failure", [RuntimeError("sampling failed"), math.inf, math.nan]
)
def test_sampler_failure_is_not_refunded(monkeypatch, failure):
    class FailingMeasurement:
        class input_domain:
            @staticmethod
            def member(values):
                return True

        def __call__(self, values):
            if isinstance(failure, Exception):
                raise failure
            return failure

    monkeypatch.setattr(
        OpenDPBoundedMean, "measurement", lambda self: (FailingMeasurement(), 0.5)
    )
    ledger = PrivacyBudget(0.5)
    query = OpenDPBoundedMean("query", 0.0, 1.0, 3, 0.5)
    with pytest.raises((RuntimeError, ValueError)):
        query.release([0.0, 0.5, 1.0], budget=ledger)
    assert ledger.epsilon_spent == 0.5
