from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from privatelabbench.cli import main
from privatelabbench.eval.predictions import (
    evaluate_prediction_csv,
    evaluate_prediction_table,
)
from privatelabbench.eval.degradation import diagnose_shift, sanitize_degradation
from privatelabbench.eval.uncertainty import BootstrapConfig
from privatelabbench.privacy.export import check_release
from privatelabbench.reports.receipt import verify_receipt


def cohort(
    tmp_path,
    name,
    *,
    groups=("a", "b"),
    sizes=(20, 20),
    errors=(0.1, 0.3),
    offset=0.0,
    id_prefix=None,
):
    rows = []
    for group, size, error in zip(groups, sizes, errors):
        for index in range(size):
            value = len(rows) * 0.1 + 0.23
            rows.append(
                {
                    "sample_id": f"{id_prefix or name}-private-row-{len(rows)}",
                    "target": value,
                    "prediction": value + error,
                    "site": group,
                    "signal": index + offset,
                    "instrument": (
                        "protected-instrument-a"
                        if offset == 0
                        else "protected-instrument-b"
                    ),
                }
            )
    path = tmp_path / f"{name}-private.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def compare(a, b, **kwargs):
    return diagnose_shift(
        str(a),
        str(b),
        target="target",
        prediction_column="prediction",
        task_type="regression",
        slice_columns=["site"],
        metric="mae",
        uncertainty_config=BootstrapConfig(
            enabled=True, resamples=100, min_samples=10, include_slices=True
        ),
        practical_thresholds={"mae": 0.01},
        **kwargs,
    )


def policy(**kwargs):
    return {
        "schema_version": "release-policy/v1",
        "id": "reviewed-shift",
        "enabled": True,
        "min_samples": 20,
        "min_cell_size": 5,
        "require_privacy_audit": False,
        "include_degradation": True,
        "slices": {"site": ["a", "b"]},
        "public_shift_features": ["signal", "instrument"],
        **kwargs,
    }


def test_globally_stable_performance_can_hide_local_degradation(tmp_path):
    a, b = cohort(tmp_path, "reference"), cohort(tmp_path, "current", errors=(0.3, 0.1))
    result = compare(a, b, independent_cohorts=True)["degradation_summary"]
    assert result["overall"]["mae"]["status"] == "within_threshold"
    assert result["slices"]["site"]["a"]["metrics"]["mae"][
        "degradation"
    ] == pytest.approx(0.2)
    assert result["slices"]["site"]["b"]["metrics"]["mae"][
        "degradation"
    ] == pytest.approx(-0.2)
    assert result["ranked_slices"][0]["value"] == "a"
    assert result["slices"]["site"]["a"]["metrics"]["mae"]["interval"]["lower"] > 0.01


def test_composition_change_can_worsen_overall_score_with_stable_slices(tmp_path):
    a = cohort(tmp_path, "reference", sizes=(30, 10), errors=(0.1, 0.5))
    b = cohort(tmp_path, "current", sizes=(10, 30), errors=(0.1, 0.5))
    summary = compare(a, b)["degradation_summary"]
    assert summary["overall"]["mae"]["degradation"] == pytest.approx(0.2)
    assert all(
        entry["metrics"]["mae"]["status"] == "within_threshold"
        for entry in summary["slices"]["site"].values()
    )
    assert summary["slices"]["site"]["a"]["prevalence_change"] == pytest.approx(-0.5)
    assert summary["slices"]["site"]["b"]["material_prevalence_change"]


def test_new_missing_and_small_slices_are_explicit_without_zero_metric_imputation(
    tmp_path,
):
    a = cohort(tmp_path, "reference")
    b = cohort(tmp_path, "current", groups=("a", "new-private-group"))
    summary = compare(a, b)["degradation_summary"]
    assert summary["slices"]["site"]["b"]["status"] == "missing_slice"
    assert summary["slices"]["site"]["new-private-group"]["status"] == "new_slice"
    assert summary["slices"]["site"]["b"]["metrics"] == {}
    assert sanitize_degradation(summary, policy())["slices"] == {}
    c = cohort(tmp_path, "small", sizes=(3, 37))
    assert (
        compare(a, c)["degradation_summary"]["slices"]["site"]["a"]["status"]
        == "skipped_min_slice_size"
    )


def test_delta_intervals_require_independence_and_withhold_overlap(tmp_path):
    a, b = cohort(tmp_path, "reference"), cohort(tmp_path, "current")
    assert (
        compare(a, b)["degradation_summary"]["overall"]["mae"]["interval"]["status"]
        == "independence_not_declared"
    )
    b = cohort(tmp_path, "current", id_prefix="reference")
    interval = compare(a, b, independent_cohorts=True)["degradation_summary"][
        "overall"
    ]["mae"]["interval"]
    assert (
        interval["status"] == "overlapping_cohorts_not_supported"
        and interval["lower"] is None
    )


def test_distribution_summaries_are_descriptive_and_constant_reference_is_explicit(
    tmp_path,
):
    a = cohort(tmp_path, "reference")
    b = cohort(tmp_path, "current", offset=10)
    summary = compare(
        a, b, numeric_metadata=["signal"], categorical_metadata=["instrument"]
    )["degradation_summary"]
    assert summary["distributions"]["signal"]["ks_distance"] == pytest.approx(0.5)
    assert summary["distributions"]["instrument"]["total_variation_distance"] == 1
    for path in (a, b):
        frame = pd.read_csv(path)
        frame["signal"] = 1
        frame.to_csv(path, index=False)
    distribution = compare(a, b, numeric_metadata=["signal"])["degradation_summary"][
        "distributions"
    ]["signal"]
    assert (
        distribution["standardized_mean_change"] is None
        and distribution["ks_distance"] == 0
    )


def test_classification_degradation_direction_and_zero_reference_denominator(tmp_path):
    a, b = tmp_path / "reference.csv", tmp_path / "current.csv"
    for path, prefix, wrong in ((a, "r", False), (b, "c", True)):
        target = np.tile([1, 0], 20)
        prediction = np.where(target == 1, 0.9, 0.1)
        if wrong:
            prediction[:20] = 1 - prediction[:20]
        pd.DataFrame(
            {
                "sample_id": [f"{prefix}-{i}" for i in range(40)],
                "target": target,
                "prediction": prediction,
            }
        ).to_csv(path, index=False)
    summary = diagnose_shift(
        str(a),
        str(b),
        target="target",
        prediction_column="prediction",
        task_type="classification",
        metric="accuracy",
        independent_cohorts=True,
        uncertainty_config=BootstrapConfig(enabled=True, resamples=100),
    )["degradation_summary"]
    change = summary["overall"]["accuracy"]
    assert (
        change["raw_delta_current_minus_reference"] == -0.5
        and change["degradation"] == 0.5
    )
    assert change["interval"]["lower"] > 0
    r = cohort(tmp_path, "perfect-reference", errors=(0, 0))
    c = cohort(tmp_path, "imperfect-current", errors=(0.1, 0.1))
    assert (
        compare(r, c)["degradation_summary"]["overall"]["mae"]["relative_degradation"]
        is None
    )


def test_dataframe_path_reuses_scoring_and_does_not_mutate_input(tmp_path):
    path = cohort(tmp_path, "reference")
    frame = pd.read_csv(path)
    original = frame.copy(deep=True)
    direct = evaluate_prediction_table(
        frame, target="target", prediction_column="prediction", task_type="regression"
    )
    csv = evaluate_prediction_csv(
        str(path),
        target="target",
        prediction_column="prediction",
        task_type="regression",
    )
    assert direct.metrics == csv.metrics
    pd.testing.assert_frame_equal(frame, original)


def test_seed_reproducibility_and_missing_values_are_not_silently_excluded(tmp_path):
    a, b = cohort(tmp_path, "reference"), cohort(tmp_path, "current", errors=(0.4, 0.7))
    assert compare(a, b, independent_cohorts=True) == compare(
        a, b, independent_cohorts=True
    )
    frame = pd.read_csv(b)
    frame.loc[0, "prediction"] = np.nan
    frame.to_csv(b, index=False)
    with pytest.raises(ValueError, match="missing values"):
        compare(a, b)


def test_run_receipts_carry_scoped_diagnostics_and_public_metadata_is_approved(
    tmp_path, monkeypatch, capsys
):
    a, b = cohort(tmp_path, "reference"), cohort(
        tmp_path, "current", errors=(0.4, 0.5), offset=10
    )
    release_path = tmp_path / "release.yaml"
    release_path.write_text(yaml.safe_dump(policy()))
    output = tmp_path / "results"
    args = [
        "plb",
        "evaluate",
        str(b),
        "--reference",
        str(a),
        "--independent-cohorts",
        "--degradation-threshold",
        "0.01",
        "--numeric-metadata",
        "signal",
        "--categorical-metadata",
        "instrument",
        "--slice",
        "site",
        "--primary-metric",
        "mae",
        "--resamples",
        "100",
        "--release-policy",
        str(release_path),
        "--output-dir",
        str(output),
    ]
    monkeypatch.setattr("sys.argv", args)
    assert main() == 0
    local = json.loads((output / "evaluation_receipt.json").read_text())
    assert local["local"]["diagnostics"]["reference_path"] == str(a.resolve())
    public_path = output / "evaluation_receipt.shareable.json"
    assert verify_receipt(public_path)["valid"]
    public = json.loads(public_path.read_text())
    summary = public["shareable"]["evaluation"]["degradation_summary"]
    import jsonschema

    schema = json.loads(
        Path(
            "privatelabbench/data/schemas/degradation-summary-v1.schema.json"
        ).read_text()
    )
    jsonschema.validate(summary, schema)
    jsonschema.validate(local["shareable"]["evaluation"]["degradation_summary"], schema)
    assert summary["overall"]["mae"]["degradation"] == pytest.approx(0.25)
    assert summary["distributions"]["instrument"]["total_variation_distance"] == 1
    text = json.dumps(public)
    assert (
        "private-row" not in text
        and a.name not in text
        and b.name not in text
        and "protected-instrument" not in text
    )
    assert (
        "Reference/current diagnostics"
        in (output / "evaluation_receipt.md").read_text()
    )
    assert "Largest degradation" in capsys.readouterr().out
    altered = deepcopy(local)
    altered["shareable"]["evaluation"]["degradation_summary"]["ranked_slices"] = [
        {"value": "private-injected-label"}
    ]
    altered["shareable"]["evaluation"]["degradation_summary"]["overall"]["mae"][
        "degradation"
    ] = 999
    decision, rebuilt = check_release(
        altered, policy(), evidence=local["local"]["release_evidence"]
    )
    assert decision.decision == "allow" and "private-injected-label" not in json.dumps(
        rebuilt
    )
    assert rebuilt["shareable"]["evaluation"]["degradation_summary"]["overall"]["mae"][
        "degradation"
    ] == pytest.approx(0.25)
    decision, withheld = check_release(
        local,
        policy(include_degradation=False),
        evidence=local["local"]["release_evidence"],
    )
    assert "degradation_summary" not in withheld["shareable"]["evaluation"]
    assert (
        check_release(
            local, policy(min_samples=41), evidence=local["local"]["release_evidence"]
        )[1]
        is None
    )


def test_small_reference_and_perturbed_metric_basis_do_not_leak_diagnostics(tmp_path):
    a, b = cohort(tmp_path, "reference"), cohort(tmp_path, "current", offset=10)
    summary = compare(a, b, categorical_metadata=["instrument"])["degradation_summary"]
    with pytest.raises(ValueError, match="Separate reference-cohort"):
        sanitize_degradation(summary, policy(require_privacy_audit=True))
    broken = deepcopy(summary)
    broken["n_reference"] = 19
    with pytest.raises(ValueError, match="Both reference"):
        sanitize_degradation(broken, policy())
    summary["distributions"]["instrument"]["min_observed_cell"] = 1
    assert "instrument" not in sanitize_degradation(summary, policy())["distributions"]
    candidate = {
        "schema_version": "evaluation-receipt/v1",
        "scope": "local",
        "shareable": {
            "evaluation": {
                "task_type": "regression",
                "input_schema": {"schema_version": "prediction-table/v1"},
                "sample_counts": {"n_samples": 40},
                "metrics": {"mae": 0.3},
                "metric_source": "reported_metrics",
                "degradation_summary": summary,
            },
            "privacy": {"mechanism": {"mode": "metric_perturbation"}},
        },
    }
    decision, exported = check_release(candidate, policy())
    assert decision.decision == "allow"
    assert exported["shareable"]["evaluation"]["degradation_summary"] == {
        "status": "withheld_metric_basis_mismatch"
    }


def test_independent_bootstrap_uses_seed_and_refuses_contradictory_interval_claims(
    tmp_path,
):
    a, b = cohort(tmp_path, "reference"), cohort(tmp_path, "current")
    for path, start, stop in ((a, 0.01, 0.2), (b, 0.1, 0.9)):
        frame = pd.read_csv(path)
        frame["prediction"] = frame["target"] + np.linspace(start, stop, len(frame))
        frame.to_csv(path, index=False)
    results = []
    for seed in (13, 14):
        results.append(
            diagnose_shift(
                str(a),
                str(b),
                target="target",
                prediction_column="prediction",
                task_type="regression",
                independent_cohorts=True,
                uncertainty_config=BootstrapConfig(
                    enabled=True, seed=seed, resamples=100
                ),
            )["degradation_summary"]
        )
    assert (
        results[0]["overall"]["mae"]["interval"]
        != results[1]["overall"]["mae"]["interval"]
    )
    results[0]["uncertainty"]["independent_cohorts_declared"] = False
    with pytest.raises(ValueError, match="confidence interval"):
        sanitize_degradation(results[0], policy())
