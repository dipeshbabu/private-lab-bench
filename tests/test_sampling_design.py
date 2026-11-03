from itertools import product
import json
from pathlib import Path
import warnings

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from privatelabbench.eval.metrics import regression_metrics
from privatelabbench.eval.paired_comparison import (
    PairedComparisonConfig,
    compare_prediction_tables,
)
from privatelabbench.eval.predictions import evaluate_prediction_table
from privatelabbench.eval.sampling import (
    MultiplicityPolicy,
    SamplingDesign,
    ResampleLimit,
    adjust_pvalues,
    bootstrap_samples,
    plan_sampling,
)
from privatelabbench.eval.uncertainty import BootstrapConfig


def design(**kwargs):
    return SamplingDesign.from_dict(
        {
            "schema_version": "sampling-design/v1",
            "unit": "patient",
            "method": "cluster_bootstrap",
            "cluster_columns": ["patient"],
            "min_independent_units": 2,
            **kwargs,
        }
    )


def clustered_frame(n_units=30, size=8):
    errors = np.random.default_rng(17).uniform(0.1, 2.0, n_units)
    target = 1e9 + np.arange(n_units * size) / 10
    return (
        pd.DataFrame(
            {
                "sample_id": [f"sample-{i}" for i in range(n_units * size)],
                "patient": np.repeat(
                    [f"protected-patient-{i}" for i in range(n_units)], size
                ),
                "target": target,
                "prediction": target + np.repeat(errors, size),
            }
        ),
        errors,
    )


def evaluate(frame, sampling=None, resamples=500):
    return evaluate_prediction_table(
        frame,
        target="target",
        prediction_column="prediction",
        task_type="regression",
        uncertainty_config=BootstrapConfig(enabled=True, resamples=resamples),
        sampling_design=sampling,
    )


def test_cluster_bootstrap_matches_scipy_reference_and_respects_correlated_units():
    frame, errors = clustered_frame(n_units=40, size=10)
    iid = evaluate(frame).uncertainty["metrics"]["mae"]
    clustered = evaluate(frame, design()).uncertainty
    interval = clustered["metrics"]["mae"]
    trusted = stats.bootstrap(
        (errors,), np.mean, method="percentile", n_resamples=5000, random_state=17
    ).confidence_interval
    assert interval["lower"] == pytest.approx(trusted.low, abs=0.04)
    assert interval["upper"] == pytest.approx(trusted.high, abs=0.04)
    assert interval["upper"] - interval["lower"] > 2.5 * (iid["upper"] - iid["lower"])
    assert clustered["n_independent_units"] == 40 and clustered["n_samples"] == 400
    assert clustered["sampling"] == "independent_clusters"


def test_whole_cluster_draws_and_sufficient_statistics_match_direct_scoring():
    frame, _ = clustered_frame(n_units=4, size=3)
    frame = frame.iloc[[0, 3, 4, 6, 7, 8, 9, 10, 11]].reset_index(drop=True)
    plan = plan_sampling(frame, design())
    y, p = frame.target.to_numpy(), frame.prediction.to_numpy()
    values = bootstrap_samples(
        y,
        p,
        task_type="regression",
        metric_names=("mae", "rmse", "r2"),
        plan=plan,
        resamples=100,
        rng=np.random.default_rng(23),
    )
    expected = {name: [] for name in values}
    rng = np.random.default_rng(23)
    for _ in range(100):
        indices = plan.draw(rng)
        frequencies = np.bincount(indices, minlength=len(frame))
        for patient in frame.patient.unique():
            assert len(set(frequencies[frame.patient == patient])) == 1
        result = regression_metrics(y[indices], p[indices])
        if np.ptp(y[indices]) == 0:
            result["r2"] = np.nan
        for name in expected:
            expected[name].append(result[name])
    for name in values:
        np.testing.assert_allclose(
            values[name], expected[name], rtol=1e-8, atol=1e-8, equal_nan=True
        )


def test_nested_bootstrap_preserves_leaf_clusters_and_rejects_crossed_units():
    frame, _ = clustered_frame(n_units=6, size=3)
    frame["site"] = np.repeat(["site-a", "site-b", "site-c"], 6)
    hierarchy = design(
        method="hierarchical_bootstrap",
        cluster_columns=["site", "patient"],
        unit="laboratory",
    )
    plan = plan_sampling(frame, hierarchy)
    assert plan.status == "evaluated" and plan.n_units == 3
    rng = np.random.default_rng(4)
    for _ in range(30):
        indices = plan.draw(rng)
        frequency = np.bincount(indices, minlength=len(frame))
        for patient in frame.patient.unique():
            assert len(set(frequency[frame.patient == patient])) == 1
    crossed = frame.copy()
    crossed.loc[6, "patient"] = crossed.loc[0, "patient"]
    assert plan_sampling(crossed, hierarchy).status == "not_supported_crossed_clusters"


def test_small_missing_stratified_and_resource_cases_return_explicit_unavailability():
    frame, _ = clustered_frame(n_units=4, size=6)
    assert (
        evaluate(frame, design(min_independent_units=5)).uncertainty["status"]
        == "skipped_min_independent_units"
    )
    missing = frame.copy()
    missing.loc[0, "patient"] = None
    assert (
        evaluate(missing, design()).uncertainty["status"]
        == "not_supported_missing_cluster_ids"
    )
    frame["stratum"] = np.repeat(["a", "a", "b", "b"], 6)
    plan = plan_sampling(frame, design(strata_column="stratum"))
    indices = plan.draw(np.random.default_rng(2))
    assert (frame.iloc[indices].stratum == "a").sum() == 12
    frame.loc[0, "stratum"] = "b"
    assert (
        plan_sampling(frame, design(strata_column="stratum")).status
        == "not_supported_nonconstant_cluster_strata"
    )
    limited = design(max_resample_rows=2)
    with pytest.raises(ResampleLimit):
        plan_sampling(frame, limited).draw(np.random.default_rng(2))
    result = evaluate(frame, limited).uncertainty
    assert (
        result["status"] == "not_supported_resource_limit" and result["metrics"] == {}
    )


def test_paired_cluster_resampling_keeps_model_covariance_and_whole_cluster_null(
    tmp_path,
):
    frame, _ = clustered_frame(n_units=3, size=4)
    frame["target"] = np.arange(len(frame), dtype=float)
    frame["prediction"] = frame.target + np.repeat([0.1, 0.4, 0.8], 4)
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    frame.to_csv(a, index=False)
    other = frame.copy()
    other["prediction"] += 0.2
    other.iloc[::-1].to_csv(b, index=False)
    config = PairedComparisonConfig(
        metric="mae", resamples=300, permutations=2000, min_samples=2
    )
    result = compare_prediction_tables(
        str(a),
        str(b),
        target="target",
        config=config,
        sampling_design=design(exchangeability="model_vectors_within_clusters"),
    )
    assert result["paired_interval"]["lower"] == pytest.approx(0.2, abs=1e-12)
    assert result["paired_interval"]["upper"] == pytest.approx(0.2, abs=1e-12)
    # Enumerate the exact 2^3 whole-cluster null as an independent reference.
    null = []
    for swaps in product((False, True), repeat=3):
        swap = np.repeat(swaps, 4)
        x = np.where(swap, other.prediction, frame.prediction)
        y = np.where(swap, frame.prediction, other.prediction)
        null.append(
            regression_metrics(frame.target.to_numpy(), y)["mae"]
            - regression_metrics(frame.target.to_numpy(), x)["mae"]
        )
    exact = np.mean(np.abs(null) >= 0.2 - 1e-12)
    assert result["randomization_test"]["p_value"] == pytest.approx(exact, abs=0.04)
    assert result["randomization_test"]["n_independent_units"] == 3
    missing = compare_prediction_tables(
        str(a), str(b), target="target", config=config, sampling_design=design()
    )
    assert missing["randomization_test"]["status"] == "exchangeability_not_declared"


@pytest.mark.parametrize(
    "method,scipy_method,dependence",
    [
        ("benjamini_hochberg", "bh", "independent_or_prds"),
        ("benjamini_yekutieli", "by", "arbitrary"),
    ],
)
def test_multiple_testing_matches_trusted_scipy_reference(
    method, scipy_method, dependence
):
    values = [0.01, 0.04, 0.03, 0.002, 0.7, 0.03]
    policy = MultiplicityPolicy.from_dict(
        {
            "schema_version": "multiplicity/v1",
            "method": method,
            "dependence": dependence,
        }
    )
    expected = (
        [0.03, 0.048, 0.045, 0.012, 0.7, 0.045]
        if scipy_method == "bh"
        else [0.0735, 0.1176, 0.11025, 0.0294, 1.0, 0.11025]
    )
    np.testing.assert_allclose(adjust_pvalues(values, policy), expected)
    if hasattr(stats, "false_discovery_control"):
        np.testing.assert_allclose(
            adjust_pvalues(values, policy),
            stats.false_discovery_control(values, method=scipy_method),
        )
    missing = adjust_pvalues([0.01, None, 0.03], policy)
    trusted = [0.03, 1.0, 0.045] if scipy_method == "bh" else [0.055, 1.0, 0.0825]
    assert (
        missing[0] == pytest.approx(trusted[0])
        and missing[1] is None
        and missing[2] == pytest.approx(trusted[2])
    )


def test_invalid_bh_dependence_and_pvalues_never_claim_control():
    with pytest.raises(ValueError, match="independent_or_prds"):
        MultiplicityPolicy.from_dict(
            {"schema_version": "multiplicity/v1", "method": "benjamini_hochberg"}
        )
    for bad in (-0.1, 1.1, float("nan"), True):
        with pytest.raises(ValueError):
            adjust_pvalues([bad], MultiplicityPolicy())


def test_slice_test_family_retains_unavailable_tests_and_marks_critical_slices(
    tmp_path,
):
    frame, _ = clustered_frame(n_units=8, size=4)
    frame["site"] = np.repeat(["a", "b"], len(frame) // 2)
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    frame.to_csv(a, index=False)
    frame["prediction"] += 0.3
    frame.to_csv(b, index=False)
    declared = design(
        exchangeability="model_vectors_within_clusters",
        critical_slices=[{"column": "site", "value": "missing-site"}],
        multiplicity={"schema_version": "multiplicity/v1"},
    )
    result = compare_prediction_tables(
        str(a),
        str(b),
        target="target",
        slice_columns=["site"],
        config=PairedComparisonConfig(
            metric="mae",
            resamples=100,
            permutations=100,
            min_samples=2,
            min_slice_size=2,
        ),
        sampling_design=declared,
    )
    assert result["multiplicity"]["n_tests"] == 2
    assert result["multiplicity"]["method"] == "benjamini_yekutieli"
    assert result["slices"]["site"]["a"]["multiplicity"]["adjusted_p_value"] is not None
    assert (
        result["slices"]["site"]["missing-site"]["inference_role"]
        == "prespecified_critical"
    )


def test_protocol_identity_changes_with_design_and_baseline_hash_is_preserved():
    from privatelabbench.protocols import (
        EvaluationProtocol,
        apply_protocol,
        resolve_protocol,
    )
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    original = resolve_protocol("plb://generic/regression@1.0.0")
    assert (
        original.sha256
        == "d1c29e51956bdc9e4e6637cd6f6ee387a7bfc233c842312c267ba5c229e414a5"
    )
    rules = original.as_dict()
    rules["version"] = "1.1.0"
    rules["sampling_design"] = design().as_dict()
    protocol = EvaluationProtocol.from_dict(rules)
    assert protocol.sha256 != original.sha256
    assert apply_protocol({}, protocol)["sampling_design"] == design().as_dict()
    with pytest.raises(ValueError, match="sampling_design conflicts"):
        apply_protocol({"sampling_design": design().as_dict()}, original)
    root = Path("privatelabbench/data/schemas")
    names = [
        "quality-policy-v1.schema.json",
        "release-policy-v1.schema.json",
        "sampling-design-v1.schema.json",
        "multiplicity-policy-v1.schema.json",
    ]
    registry = Registry().with_resources(
        (name, Resource.from_contents(json.loads((root / name).read_text())))
        for name in names
    )
    schema = json.loads((root / "evaluation-protocol-v1.schema.json").read_text())
    Draft202012Validator(schema, registry=registry).validate(protocol.as_dict())


@pytest.mark.parametrize(
    "update",
    [
        {"cluster_columns": ["a", "b"]},
        {"sampling_level": "row"},
        {"min_independent_units": 1},
        {"min_independent_units": True},
        {"resample_rows_within_leaf": True},
        {"method": "not-implemented"},
        {"cluster_columns": ["a", "a"]},
        {"strata_column": 0},
    ],
)
def test_unsupported_or_invalid_designs_never_revert_to_row_bootstrap(update):
    with pytest.raises(ValueError):
        design(**update)


def test_clustered_cohort_deltas_are_not_replaced_with_iid_intervals(tmp_path):
    from privatelabbench.eval.degradation import diagnose_shift

    a, _ = clustered_frame(n_units=30, size=8)
    b, _ = clustered_frame(n_units=30, size=8)
    b["sample_id"] = "current-" + b.sample_id
    b["patient"] = "current-" + b.patient
    b["prediction"] += 0.4
    path_a, path_b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.to_csv(path_a, index=False)
    b.to_csv(path_b, index=False)
    options = {
        "target": "target",
        "prediction_column": "prediction",
        "task_type": "regression",
        "independent_cohorts": True,
        "uncertainty_config": BootstrapConfig(enabled=True, resamples=300),
    }
    clustered = diagnose_shift(
        str(path_a), str(path_b), sampling_design=design(), **options
    )["degradation_summary"]
    iid = diagnose_shift(str(path_a), str(path_b), **options)["degradation_summary"]
    interval = clustered["overall"]["mae"]["interval"]
    row_interval = iid["overall"]["mae"]["interval"]
    assert (
        interval["status"] == "evaluated"
        and interval["n_independent_units_reference"] == 30
    )
    assert interval["upper"] - interval["lower"] > 2 * (
        row_interval["upper"] - row_interval["lower"]
    )
    assert (
        clustered["uncertainty"]["method"] == "independent_cluster_percentile_bootstrap"
    )
    b["patient"] = a.patient
    b.to_csv(path_b, index=False)
    overlapping = diagnose_shift(
        str(path_a), str(path_b), sampling_design=design(), **options
    )["degradation_summary"]
    assert (
        overlapping["overall"]["mae"]["interval"]["status"]
        == "overlapping_cohorts_not_supported"
    )


def test_public_inference_uses_approved_complete_family_and_recomputes_adjustments(
    tmp_path,
):
    from copy import deepcopy
    from privatelabbench.privacy.export import check_release
    from privatelabbench.reports.paired_comparison import (
        build_paired_comparison_artifact,
    )

    frame, _ = clustered_frame(n_units=40, size=4)
    frame["site"] = np.repeat(["a", "b"], len(frame) // 2)
    a, b = tmp_path / "private-a.csv", tmp_path / "private-b.csv"
    frame.to_csv(a, index=False)
    frame["prediction"] += 0.3
    frame.to_csv(b, index=False)
    declared = design(
        exchangeability="model_vectors_within_clusters",
        multiplicity={"schema_version": "multiplicity/v1"},
    )
    result = compare_prediction_tables(
        str(a),
        str(b),
        target="target",
        slice_columns=["site"],
        config=PairedComparisonConfig(
            metric="mae",
            resamples=100,
            permutations=100,
            min_samples=2,
            min_slice_size=2,
            include_slice_uncertainty=True,
        ),
        sampling_design=declared,
    )
    artifact = build_paired_comparison_artifact(result=result, path_a=a, path_b=b)
    approved = {
        "schema_version": "release-policy/v1",
        "id": "reviewed-clustered-results",
        "enabled": True,
        "min_samples": 20,
        "min_cell_size": 5,
        "require_privacy_audit": False,
        "slices": {"site": ["a", "b"]},
        "include_slice_inference": True,
        "include_multiplicity": True,
    }
    decision, public = check_release(artifact, approved)
    assert decision.decision == "allow"
    shared = public["shareable"]
    assert shared["paired_interval"]["n_independent_units"] == 40
    assert shared["multiplicity"]["n_tests"] == 2
    assert shared["slices"]["site"]["a"]["multiplicity"]["adjusted_p_value"] is not None
    assert "protected-patient" not in json.dumps(
        public
    ) and "sampling_design" not in json.dumps(public)
    modified = deepcopy(artifact)
    modified["shareable"]["slices"]["site"]["a"]["multiplicity"]["adjusted_p_value"] = 1
    _, recomputed = check_release(modified, approved)
    assert (
        recomputed["shareable"]["slices"]["site"]["a"]["multiplicity"]
        == shared["slices"]["site"]["a"]["multiplicity"]
    )
    _, default = check_release(
        artifact,
        {**approved, "include_slice_inference": False, "include_multiplicity": False},
    )
    assert (
        "multiplicity" not in default["shareable"]
        and "paired_interval" not in default["shareable"]["slices"]["site"]["a"]
    )
    _, incomplete = check_release(artifact, {**approved, "slices": {"site": ["a"]}})
    assert (
        incomplete["shareable"]["slices"] == {}
        and "multiplicity" not in incomplete["shareable"]
    )
    modified["shareable"]["paired_interval"]["n_independent_units"] = 3
    assert check_release(modified, approved)[1] is None


def test_cli_generation_receipts_and_identifier_spelling_preserve_design(
    tmp_path, monkeypatch, capsys
):
    from privatelabbench.cli import main
    from privatelabbench.reports.receipt import verify_receipt
    import yaml

    frame, _ = clustered_frame(n_units=30, size=2)
    frame.loc[:2, "sample_id"] = ["001", "01", "1"]
    path = tmp_path / "private.csv"
    frame.to_csv(path, index=False)
    declaration = tmp_path / "sampling.yaml"
    declaration.write_text(yaml.safe_dump(design().as_dict()))
    output = tmp_path / "results"
    monkeypatch.setattr(
        "sys.argv",
        [
            "plb",
            "evaluate",
            str(path),
            "--task-type",
            "regression",
            "--sampling-design",
            str(declaration),
            "--resamples",
            "100",
            "--output-dir",
            str(output),
        ],
    )
    assert main() == 0
    assert "Independent units    30" in capsys.readouterr().out
    receipt = output / "evaluation_receipt.json"
    assert verify_receipt(receipt)["valid"]
    local = json.loads(receipt.read_text())
    assert local["local"]["uncertainty"]["n_independent_units"] == 30
    assert local["local"]["config_snapshot"]["sampling_design"]["unit"] == "patient"


def test_clustered_classification_matches_unit_reference_and_rare_class_is_inconclusive():
    from sklearn.exceptions import UndefinedMetricWarning

    units, repeats = 40, 5
    target_units = np.tile([0, 1], units // 2)
    scores = np.where(target_units == 1, 0.9, 0.1)
    scores[[0, 3, 6, 9]] = 1 - scores[[0, 3, 6, 9]]
    frame = pd.DataFrame(
        {
            "sample_id": [f"id-{i}" for i in range(units * repeats)],
            "patient": np.repeat([f"patient-{i}" for i in range(units)], repeats),
            "target": np.repeat(target_units, repeats),
            "prediction": np.repeat(scores, repeats),
        }
    )
    result = evaluate_prediction_table(
        frame,
        target="target",
        prediction_column="prediction",
        task_type="classification",
        sampling_design=design(),
        uncertainty_config=BootstrapConfig(enabled=True, resamples=300),
    )
    correct = ((scores >= 0.5) == target_units).astype(float)
    trusted = stats.bootstrap(
        (correct,), np.mean, method="percentile", n_resamples=5000, random_state=19
    ).confidence_interval
    interval = result.uncertainty["metrics"]["accuracy"]
    assert interval["lower"] == pytest.approx(trusted.low, abs=0.04)
    assert interval["upper"] == pytest.approx(trusted.high, abs=0.04)
    frame["target"] = 0
    frame.loc[frame.patient == "patient-0", "target"] = 1
    frame["prediction"] = np.where(frame.target == 1, 0.9, 0.1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UndefinedMetricWarning)
        rare = evaluate_prediction_table(
            frame,
            target="target",
            prediction_column="prediction",
            task_type="classification",
            sampling_design=design(),
            uncertainty_config=BootstrapConfig(enabled=True, resamples=200),
        )
    assert (
        rare.uncertainty["metrics"]["auroc"]["status"] == "insufficient_valid_resamples"
    )
    assert rare.uncertainty["metrics"]["auroc"]["lower"] is None


def test_hierarchical_intervals_and_explicit_leaf_row_sampling_have_scoped_limits(
    tmp_path,
):
    frame, _ = clustered_frame(n_units=12, size=4)
    frame["site"] = np.repeat(["site-a", "site-b", "site-c"], 16)
    hierarchy = design(
        method="hierarchical_bootstrap",
        cluster_columns=["site", "patient"],
        unit="laboratory",
        exchangeability="model_vectors_within_clusters",
    )
    result = evaluate(frame, hierarchy, resamples=100)
    assert result.uncertainty["method"] == "hierarchical_percentile_bootstrap"
    assert result.uncertainty["n_independent_units"] == 3
    assert result.uncertainty["metrics"]["mae"]["status"] == "evaluated"
    plan = plan_sampling(
        frame,
        design(
            method="hierarchical_bootstrap",
            cluster_columns=["site", "patient"],
            unit="laboratory",
            resample_rows_within_leaf=True,
        ),
    )
    frequency = np.bincount(plan.draw(np.random.default_rng(11)), minlength=len(frame))
    assert any(
        len(set(frequency[frame.patient == patient])) > 1
        for patient in frame.patient.unique()
    )
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    frame.to_csv(a, index=False)
    frame["prediction"] += 0.2
    frame.to_csv(b, index=False)
    paired = compare_prediction_tables(
        str(a),
        str(b),
        target="target",
        config=PairedComparisonConfig(
            metric="mae", resamples=100, permutations=100, min_samples=2
        ),
        sampling_design=hierarchy,
    )
    assert paired["paired_interval"]["status"] == "evaluated"
    assert paired["randomization_test"]["status"] == "not_supported_nested_permutation"
    assert paired["randomization_test"]["p_value"] is None


def test_critical_family_includes_missing_tests_and_zero_permutations_do_not_claim_fdr(
    tmp_path,
):
    frame, _ = clustered_frame(n_units=8, size=4)
    frame["site"] = np.repeat(["a", "b"], len(frame) // 2)
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    frame.to_csv(a, index=False)
    frame["prediction"] += 0.2
    frame.to_csv(b, index=False)
    declared = design(
        exchangeability="model_vectors_within_clusters",
        critical_slices=[
            {"column": "site", "value": "a"},
            {"column": "site", "value": "absent"},
        ],
        multiplicity={"schema_version": "multiplicity/v1", "family": "critical_slices"},
    )
    for permutations in (100, 0):
        result = compare_prediction_tables(
            str(a),
            str(b),
            target="target",
            config=PairedComparisonConfig(
                metric="mae", resamples=100, permutations=permutations, min_samples=2
            ),
            sampling_design=declared,
        )
        family = result["multiplicity"]
        assert family["n_tests"] == 2
        assert family["n_missing_tests"] == (1 if permutations else 2)
        assert (
            result["slices"]["site"]["absent"]["multiplicity"]["adjusted_p_value"]
            is None
        )
        assert family["status"] == ("evaluated" if permutations else "not_testable")
