from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from privatelabbench.eval.predictions import evaluate_prediction_csv
from privatelabbench.eval.uncertainty import BootstrapConfig, bootstrap_metric_intervals
from privatelabbench.runner import run_config
from privatelabbench.validation import validate_config


def test_regression_bootstrap_is_reproducible_and_bounded():
    config = BootstrapConfig(enabled=True, resamples=200, seed=7, min_samples=5)
    first = evaluate_prediction_csv(
        "examples/tabular_predictions_demo.csv",
        target="target",
        prediction_column="prediction",
        task_type="regression",
        require_sample_id=True,
        uncertainty_config=config,
    )
    second = evaluate_prediction_csv(
        "examples/tabular_predictions_demo.csv",
        target="target",
        prediction_column="prediction",
        task_type="regression",
        require_sample_id=True,
        uncertainty_config=config,
    )

    assert first.uncertainty == second.uncertainty
    assert first.uncertainty["schema_version"] == "uncertainty/v1"
    assert first.uncertainty["sampling"] == "iid_rows"
    assert first.uncertainty["metric_basis"] == "clean_metrics"
    for name in ("mae", "rmse", "r2"):
        interval = first.uncertainty["metrics"][name]
        assert interval["status"] == "evaluated"
        assert interval["valid_resamples"] >= 160
        assert interval["lower"] <= interval["upper"]


def test_binary_bootstrap_is_stratified_and_keeps_auroc_defined(tmp_path):
    csv_path = tmp_path / "binary.csv"
    rows = ["sample_id,target,score"]
    for index in range(20):
        target = "negative" if index % 2 == 0 else "positive"
        score = 0.1 + 0.02 * index if target == "negative" else 0.6 + 0.015 * index
        rows.append(f"s{index:02d},{target},{min(score, 0.99):.4f}")
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    result = evaluate_prediction_csv(
        str(csv_path),
        target="target",
        prediction_column="score",
        task_type="classification",
        class_labels=["negative", "positive"],
        require_sample_id=True,
        uncertainty_config=BootstrapConfig(enabled=True, resamples=100, seed=3, min_samples=10),
    )

    assert result.uncertainty["sampling"] == "stratified_by_target"
    assert result.uncertainty["metrics"]["auroc"]["status"] == "evaluated"
    assert result.uncertainty["metrics"]["auroc"]["valid_resamples"] == 100


def test_multiclass_bootstrap_and_slice_uncertainty():
    result = evaluate_prediction_csv(
        "examples/multiclass_predictions_demo.csv",
        target="target",
        prediction_columns=["p_alpha", "p_beta", "p_gamma"],
        task_type="multiclass",
        class_labels=["alpha", "beta", "gamma"],
        require_sample_id=True,
        slice_columns=["site"],
        min_slice_size=2,
        uncertainty_config=BootstrapConfig(
            enabled=True,
            resamples=100,
            seed=5,
            min_samples=2,
            include_slices=True,
        ),
    )

    assert result.uncertainty["metrics"]["accuracy"]["status"] == "evaluated"
    north = result.slice_metrics["site"]["north"]
    assert north["status"] == "evaluated"
    assert north["uncertainty"]["status"] == "evaluated"
    assert north["uncertainty"]["metrics"]["log_loss"]["valid_resamples"] == 100


def test_uncertainty_skips_tiny_samples_explicitly():
    result = bootstrap_metric_intervals(
        task_type="regression",
        y_true=np.array([0.0, 1.0, 2.0]),
        predictions=np.array([0.1, 0.9, 2.1]),
        config=BootstrapConfig(enabled=True, resamples=100, min_samples=10),
    )
    assert result["status"] == "skipped_min_samples"
    assert result["n_samples"] == 3
    assert result["metrics"] == {}


def _write_uncertainty_config(tmp_path: Path, *, privacy_mode: str = "none") -> Path:
    config_path = tmp_path / f"uncertainty-{privacy_mode}.yaml"
    report_path = tmp_path / f"{privacy_mode}.json"
    markdown_path = tmp_path / f"{privacy_mode}.md"
    manifest_path = tmp_path / f"{privacy_mode}_manifest.json"
    audit_path = tmp_path / f"{privacy_mode}_audit.jsonl"
    config_path.write_text(
        f"""
project: uncertainty-test
task: tabular
input:
  path: examples/tabular_predictions_demo.csv
  sample_id_column: sample_id
  require_sample_id: true
  target_column: target
  prediction_column: prediction
  task_type: regression
  slice_columns:
    - site
uncertainty:
  enabled: true
  method: percentile_bootstrap
  confidence_level: 0.95
  resamples: 100
  seed: 11
  min_samples: 5
  include_slices: false
privacy:
  mode: {privacy_mode}
  epsilon: 8
  sensitivity: 1
report:
  markdown: {markdown_path}
  json: {report_path}
  manifest: {manifest_path}
audit:
  path: {audit_path}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return config_path


def test_config_run_puts_uncertainty_in_report_and_shareable_receipt(tmp_path):
    config_path = _write_uncertainty_config(tmp_path)
    assert validate_config(str(config_path)).valid
    summary = run_config(str(config_path))
    report = json.loads(Path(summary["json_report"]).read_text(encoding="utf-8"))
    shareable_path = Path(summary["manifest"]).with_name("none_receipt.shareable.json")
    shareable = json.loads(shareable_path.read_text(encoding="utf-8"))

    assert report["result"]["uncertainty"]["status"] == "evaluated"
    assert shareable["shareable"]["evaluation"]["uncertainty"]["status"] == "evaluated"
    assert shareable["shareable"]["evaluation"]["uncertainty"]["metrics"]["rmse"]["lower"] is not None
    assert shareable["shareable"]["evaluation"]["input_schema"]["sample_id_column"] == "sample_id"
    assert "s01" not in json.dumps(shareable)


def test_shareable_receipt_does_not_attach_clean_ci_to_perturbed_metric(tmp_path):
    config_path = _write_uncertainty_config(tmp_path, privacy_mode="metric_perturbation")
    summary = run_config(str(config_path))
    shareable_path = Path(summary["manifest"]).with_name("metric_perturbation_receipt.shareable.json")
    shareable = json.loads(shareable_path.read_text(encoding="utf-8"))
    uncertainty = shareable["shareable"]["evaluation"]["uncertainty"]

    assert uncertainty["status"] == "withheld_metric_basis_mismatch"
    assert "metrics" not in uncertainty


def test_invalid_uncertainty_config_fails_validation(tmp_path):
    config_path = _write_uncertainty_config(tmp_path)
    content = config_path.read_text(encoding="utf-8").replace("resamples: 100", "resamples: 10")
    config_path.write_text(content, encoding="utf-8")
    validation = validate_config(str(config_path))
    assert not validation.valid
    assert any("uncertainty.resamples must be at least 100" in error for error in validation.errors)
