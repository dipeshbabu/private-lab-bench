import json

import numpy as np
import pandas as pd
import pytest
from scipy.stats import spearmanr

from privatelabbench.eval.degradation import diagnose_shift
from privatelabbench.eval.metrics import regression_metrics, spearman_correlation
from privatelabbench.eval.paired_comparison import (
    PairedComparisonConfig,
    compare_prediction_tables,
)
from privatelabbench.eval.predictions import (
    evaluate_prediction_table,
)
from privatelabbench.eval.sampling import SamplingDesign
from privatelabbench.eval.uncertainty import BootstrapConfig, bootstrap_metric_intervals


def test_average_tied_ranks_match_scipy_and_input_arrays_are_immutable():
    generator = np.random.default_rng(13)
    for n in (2, 5, 101, 1000):
        y = generator.integers(0, 8, n).astype(float)
        p = generator.normal(size=n)
        y.flags.writeable = False
        p.flags.writeable = False
        expected = spearmanr(y, p).statistic
        assert spearman_correlation(y, p) == pytest.approx(
            expected, abs=1e-12, nan_ok=True
        )
        assert spearman_correlation(y, 3 * p + 10) == pytest.approx(
            expected, abs=1e-12, nan_ok=True
        )
        assert spearman_correlation(y, -p) == pytest.approx(
            -expected, abs=1e-12, nan_ok=True
        )


def test_undefined_rank_correlation_is_not_zero_and_nonfinite_values_are_not_omitted():
    assert np.isnan(spearman_correlation(np.ones(10), np.arange(10)))
    assert np.isnan(spearman_correlation(np.arange(10), np.ones(10)))
    assert np.isnan(spearman_correlation(np.array([1.0]), np.array([2.0])))
    with pytest.raises(ValueError):
        spearman_correlation(np.array([1, np.nan]), np.array([1, 2]))


def test_default_regression_does_not_compute_spearman(monkeypatch):
    import privatelabbench.eval.metrics as module

    def unexpected(*args):
        raise AssertionError("Unrequested rank correlation")

    monkeypatch.setattr(module, "spearman_correlation", unexpected)
    assert set(regression_metrics(np.arange(20.0), np.arange(20.0) + 0.2)) == {
        "mae",
        "rmse",
        "r2",
    }
    with pytest.raises(ValueError):
        regression_metrics(
            np.arange(20.0), np.arange(20.0), metric_names={"mae": {"max": 1}}
        )


def test_selected_bootstrap_matches_a_direct_scipy_reference():
    generator = np.random.default_rng(17)
    y = generator.normal(size=55)
    p = 0.6 * y + generator.normal(size=55)
    config = BootstrapConfig(enabled=True, resamples=100, seed=13)
    result = bootstrap_metric_intervals(
        task_type="regression",
        y_true=y,
        predictions=p,
        config=config,
        metric_names=["spearman"],
    )
    rng = np.random.default_rng(13)
    values = []
    for _ in range(100):
        selected = rng.integers(0, len(y), len(y))
        values.append(spearmanr(y[selected], p[selected]).statistic)
    expected = np.quantile(values, [0.025, 0.975])
    assert set(result["metrics"]) == {"spearman"}
    assert [
        result["metrics"]["spearman"][key] for key in ("lower", "upper")
    ] == pytest.approx(expected, abs=1e-12)


def test_cluster_rank_bootstrap_and_single_assay_guard():
    generator = np.random.default_rng(19)
    n = 90
    y = generator.normal(size=n)
    p = y + generator.normal(size=n)
    frame = pd.DataFrame(
        {
            "sample_id": [f"s-{index}" for index in range(n)],
            "target": y,
            "prediction": p,
            "position": np.repeat(np.arange(30), 3),
            "assay": "one-assay",
        }
    )
    design = SamplingDesign.from_dict(
        {
            "schema_version": "sampling-design/v1",
            "unit": "position",
            "method": "cluster_bootstrap",
            "cluster_columns": ["position"],
            "min_independent_units": 2,
        }
    )
    result = evaluate_prediction_table(
        frame,
        target="target",
        prediction_column="prediction",
        task_type="regression",
        metric_names=["spearman"],
        evaluation_group={"column": "assay", "max_groups": 1},
        uncertainty_config=BootstrapConfig(enabled=True, resamples=100),
        sampling_design=design,
    )
    assert set(result.metrics) == {"spearman"}
    assert (
        result.uncertainty["n_independent_units"] == 30
        and result.uncertainty["metrics"]["spearman"]["status"] == "evaluated"
    )
    frame.loc[0, "assay"] = "another-assay"
    with pytest.raises(ValueError, match="assays separately"):
        evaluate_prediction_table(
            frame,
            target="target",
            prediction_column="prediction",
            task_type="regression",
            metric_names=["spearman"],
            evaluation_group={"column": "assay", "max_groups": 1},
        )


def test_paired_rank_bootstrap_randomization_and_assay_scope(tmp_path):
    generator = np.random.default_rng(23)
    n = 65
    y = generator.normal(size=n)
    a = pd.DataFrame(
        {
            "sample_id": [f"s-{index}" for index in range(n)],
            "target": y,
            "prediction": y + generator.normal(scale=0.3, size=n),
            "assay": "001",
        }
    )
    b = a.copy()
    b["prediction"] = generator.normal(size=n)
    paths = [tmp_path / "a.csv", tmp_path / "b.csv"]
    for path, frame in zip(paths, (a, b)):
        frame.to_csv(path, index=False)
    result = compare_prediction_tables(
        *map(str, paths),
        target="target",
        task_type="regression",
        class_labels=[],
        config=PairedComparisonConfig(
            metric="spearman", resamples=100, permutations=100
        ),
        evaluation_group={"column": "assay", "max_groups": 1},
    )
    assert result["improvement_a_over_b"] > 0.5
    assert result["paired_interval"]["upper"] > result["paired_interval"]["lower"]
    assert result["randomization_test"]["status"] == "evaluated"
    b["assay"] = "002"
    b.to_csv(paths[1], index=False)
    with pytest.raises(ValueError):
        compare_prediction_tables(
            *map(str, paths),
            target="target",
            task_type="regression",
            config=PairedComparisonConfig(
                metric="spearman", resamples=100, permutations=0
            ),
            evaluation_group={"column": "assay", "max_groups": 1},
        )


def test_rank_cohort_diagnostics_do_not_add_unrequested_scale_metrics(tmp_path):
    generator = np.random.default_rng(29)
    paths = []
    for index, noise in enumerate((0.2, 1.3)):
        y = generator.normal(size=60)
        frame = pd.DataFrame(
            {
                "sample_id": [f"cohort-{index}-{row}" for row in range(60)],
                "target": y,
                "prediction": y + generator.normal(scale=noise, size=60),
                "assay": "single-assay",
            }
        )
        path = tmp_path / f"cohort-{index}.csv"
        frame.to_csv(path, index=False)
        paths.append(path)
    result = diagnose_shift(
        *map(str, paths),
        target="target",
        prediction_column="prediction",
        task_type="regression",
        metric="spearman",
        uncertainty_config=BootstrapConfig(enabled=True, resamples=100),
        independent_cohorts=True,
        evaluation_group={"column": "assay", "max_groups": 1},
    )
    summary = result["degradation_summary"]
    assert summary["metric"] == "spearman"
    assert '"rmse"' not in json.dumps(summary) and '"mae"' not in json.dumps(summary)
