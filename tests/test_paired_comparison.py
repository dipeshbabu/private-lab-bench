from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from privatelabbench.cli import build_parser
from privatelabbench.compare import compare_prediction_files
from privatelabbench.eval.paired_comparison import PairedComparisonConfig, compare_prediction_tables
from privatelabbench.reports.integrity import verify_report


def _write_regression_pair(tmp_path: Path, *, reordered_b: bool = True) -> tuple[Path, Path]:
    n = 40
    target = np.linspace(-1.0, 1.0, n)
    sign = np.where(np.arange(n) % 2 == 0, 1.0, -1.0)
    a = pd.DataFrame(
        {
            "sample_id": [f"s{i:03d}" for i in range(n)],
            "target": target,
            "prediction": target + 0.05 * sign,
            "site": ["north"] * 20 + ["south"] * 20,
        }
    )
    b = a.copy()
    b["prediction"] = target + 0.15 * sign
    if reordered_b:
        b = b.sample(frac=1.0, random_state=3).reset_index(drop=True)
    path_a = tmp_path / "a.csv"
    path_b = tmp_path / "b.csv"
    a.to_csv(path_a, index=False)
    b.to_csv(path_b, index=False)
    return path_a, path_b


def test_regression_comparison_aligns_by_id_and_reports_paired_improvement(tmp_path):
    path_a, path_b = _write_regression_pair(tmp_path)
    result = compare_prediction_tables(
        str(path_a),
        str(path_b),
        target="target",
        task_type="regression",
        slice_columns=["site"],
        model_a_name="candidate",
        model_b_name="baseline",
        config=PairedComparisonConfig(
            metric="rmse",
            resamples=200,
            permutations=200,
            seed=7,
            min_samples=20,
            practical_threshold=0.05,
            min_slice_size=5,
        ),
    )

    assert result["alignment"]["status"] == "exact_sample_id_match"
    assert result["alignment"]["dropped_samples"] == 0
    assert result["direction"] == "lower_is_better"
    assert result["model_a"]["selected_metric"] == pytest.approx(0.05)
    assert result["model_b"]["selected_metric"] == pytest.approx(0.15)
    assert result["improvement_a_over_b"] == pytest.approx(0.10)
    assert result["paired_interval"]["status"] == "evaluated"
    assert result["paired_interval"]["lower"] > 0.05
    assert result["decision"]["confidence_interval"] == "a_exceeds_threshold"
    assert result["randomization_test"]["status"] == "evaluated"
    assert result["randomization_test"]["p_value"] < 0.05
    assert result["slices"]["site"]["north"]["winner"] == "a"


def test_r2_paired_bootstrap_has_valid_resamples(tmp_path):
    path_a, path_b = _write_regression_pair(tmp_path)
    result = compare_prediction_tables(
        str(path_a),
        str(path_b),
        target="target",
        task_type="regression",
        config=PairedComparisonConfig(metric="r2", resamples=100, permutations=0, min_samples=20),
    )
    assert result["direction"] == "higher_is_better"
    assert result["paired_interval"]["status"] == "evaluated"
    assert result["paired_interval"]["valid_resamples"] >= 80
    assert result["improvement_a_over_b"] > 0


def test_exact_tie_is_not_declared_model_a_superior(tmp_path):
    path_a, path_b = _write_regression_pair(tmp_path, reordered_b=False)
    table = pd.read_csv(path_a)
    table.to_csv(path_b, index=False)
    result = compare_prediction_tables(
        str(path_a),
        str(path_b),
        target="target",
        task_type="regression",
        config=PairedComparisonConfig(metric="mae", resamples=100, permutations=100, min_samples=20),
    )
    assert result["improvement_a_over_b"] == pytest.approx(0.0)
    assert result["paired_interval"]["lower"] == pytest.approx(0.0)
    assert result["paired_interval"]["upper"] == pytest.approx(0.0)
    assert result["decision"]["point_estimate"] == "below_practical_threshold"
    assert result["decision"]["confidence_interval"] == "inconclusive"
    assert result["randomization_test"]["p_value"] == pytest.approx(1.0)


def test_binary_auroc_comparison_uses_paired_stratified_bootstrap(tmp_path):
    n = 40
    labels = np.array(["negative", "positive"] * 20)
    a_score = np.where(labels == "positive", 0.9, 0.1)
    b_score = np.where(labels == "positive", 0.7, 0.3).astype(float)
    # Deliberately damage ranking for a subset while keeping valid probabilities.
    b_score[[1, 5, 9, 13]] = 0.2
    b_score[[0, 4, 8, 12]] = 0.8
    base = pd.DataFrame({"sample_id": [f"b{i}" for i in range(n)], "target": labels})
    a = base.assign(prediction=a_score)
    b = base.assign(prediction=b_score).sample(frac=1.0, random_state=9)
    path_a, path_b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.to_csv(path_a, index=False)
    b.to_csv(path_b, index=False)

    result = compare_prediction_tables(
        str(path_a),
        str(path_b),
        target="target",
        task_type="classification",
        class_labels=["negative", "positive"],
        config=PairedComparisonConfig(metric="auroc", resamples=100, permutations=100, min_samples=20),
    )
    assert result["direction"] == "higher_is_better"
    assert result["model_a"]["selected_metric"] > result["model_b"]["selected_metric"]
    assert result["improvement_a_over_b"] > 0
    assert result["paired_interval"]["sampling"] == "stratified_by_target"
    assert result["paired_interval"]["valid_resamples"] == 100


def test_multiclass_log_loss_comparison(tmp_path):
    labels = ["alpha", "beta", "gamma"]
    rows_a = []
    rows_b = []
    for index in range(60):
        target = labels[index % 3]
        correct = index % 3
        prob_a = np.full(3, 0.1)
        prob_a[correct] = 0.8
        prob_b = np.full(3, 0.2)
        prob_b[correct] = 0.6
        rows_a.append([f"m{index}", target, *prob_a])
        rows_b.append([f"m{index}", target, *prob_b])
    columns = ["sample_id", "target", "p_alpha", "p_beta", "p_gamma"]
    path_a, path_b = tmp_path / "a.csv", tmp_path / "b.csv"
    pd.DataFrame(rows_a, columns=columns).to_csv(path_a, index=False)
    pd.DataFrame(rows_b[::-1], columns=columns).to_csv(path_b, index=False)

    result = compare_prediction_tables(
        str(path_a),
        str(path_b),
        target="target",
        prediction_column=None,
        prediction_columns=["p_alpha", "p_beta", "p_gamma"],
        task_type="multiclass",
        class_labels=labels,
        config=PairedComparisonConfig(metric="log_loss", resamples=100, permutations=100, min_samples=20),
    )
    assert result["direction"] == "lower_is_better"
    assert result["improvement_a_over_b"] > 0
    assert result["paired_interval"]["status"] == "evaluated"


def test_mismatched_ids_are_rejected_without_silent_inner_join(tmp_path):
    path_a, path_b = _write_regression_pair(tmp_path, reordered_b=False)
    b = pd.read_csv(path_b)
    b.loc[0, "sample_id"] = "only-in-b"
    b.to_csv(path_b, index=False)
    with pytest.raises(ValueError, match="exactly the same sample IDs"):
        compare_prediction_tables(str(path_a), str(path_b), target="target", task_type="regression")


def test_target_mismatch_is_rejected(tmp_path):
    path_a, path_b = _write_regression_pair(tmp_path, reordered_b=False)
    b = pd.read_csv(path_b)
    b.loc[3, "target"] += 1.0
    b.to_csv(path_b, index=False)
    with pytest.raises(ValueError, match="Targets disagree"):
        compare_prediction_tables(str(path_a), str(path_b), target="target", task_type="regression")


def test_slice_metadata_mismatch_is_rejected(tmp_path):
    path_a, path_b = _write_regression_pair(tmp_path, reordered_b=False)
    b = pd.read_csv(path_b)
    b.loc[3, "site"] = "different"
    b.to_csv(path_b, index=False)
    with pytest.raises(ValueError, match="Slice metadata column 'site' disagrees"):
        compare_prediction_tables(
            str(path_a), str(path_b), target="target", task_type="regression", slice_columns=["site"]
        )


def test_noninferiority_decision_uses_paired_interval(tmp_path):
    n = 40
    target = np.linspace(0.0, 1.0, n)
    sign = np.where(np.arange(n) % 2 == 0, 1.0, -1.0)
    ids = [f"n{i}" for i in range(n)]
    a = pd.DataFrame({"sample_id": ids, "target": target, "prediction": target + 0.06 * sign})
    b = pd.DataFrame({"sample_id": ids, "target": target, "prediction": target + 0.05 * sign})
    path_a, path_b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.to_csv(path_a, index=False)
    b.to_csv(path_b, index=False)
    result = compare_prediction_tables(
        str(path_a),
        str(path_b),
        target="target",
        task_type="regression",
        config=PairedComparisonConfig(
            metric="mae",
            resamples=100,
            permutations=0,
            min_samples=20,
            noninferiority_margin=0.02,
        ),
    )
    assert result["improvement_a_over_b"] == pytest.approx(-0.01)
    assert result["decision"]["noninferiority"]["status"] == "a_noninferior"


def test_comparison_artifacts_are_verifiable_and_shareable_boundary_is_clean(tmp_path):
    path_a, path_b = _write_regression_pair(tmp_path)
    report = tmp_path / "comparison.md"
    json_report = tmp_path / "comparison.json"
    result = compare_prediction_files(
        str(path_a),
        str(path_b),
        target="target",
        prediction_column="prediction",
        prediction_columns=None,
        sample_id_column="sample_id",
        task_type="regression",
        class_labels=None,
        slice_columns=["site"],
        model_a_name="candidate",
        model_b_name="baseline",
        metric="rmse",
        confidence_level=0.95,
        resamples=100,
        permutations=100,
        seed=13,
        min_samples=20,
        practical_threshold=0.0,
        noninferiority_margin=None,
        include_slice_uncertainty=False,
        min_slice_size=5,
        markdown_path=str(report),
        json_path=str(json_report),
    )
    local = json.loads(json_report.read_text(encoding="utf-8"))
    shareable_path = Path(result["shareable_json_report"])
    shareable = json.loads(shareable_path.read_text(encoding="utf-8"))
    serialized = json.dumps(shareable)

    assert local["scope"] == "local"
    assert "local" in local
    assert shareable["scope"] == "shareable"
    assert "local" not in shareable
    assert str(path_a) not in serialized
    assert str(path_b) not in serialized
    assert "s000" not in serialized
    assert verify_report(str(shareable_path))["valid"] is True
    assert "Positive `improvement_a_over_b` always means Model A is better" in report.read_text(encoding="utf-8")


def test_legacy_compare_cli_shape_remains_supported():
    parser = build_parser()
    args = parser.parse_args(["compare", "a.yaml", "b.yaml"])
    assert args.inputs == ["a.yaml", "b.yaml"]
    assert args.target is None


def test_paired_compare_cli_shape():
    parser = build_parser()
    args = parser.parse_args(
        [
            "compare",
            "a.csv",
            "b.csv",
            "--target",
            "target",
            "--metric",
            "auroc",
            "--task-type",
            "classification",
        ]
    )
    assert args.inputs == ["a.csv", "b.csv"]
    assert args.target == "target"
    assert args.metric == "auroc"
