import json
import math

import numpy as np
import pandas as pd
import pytest
import yaml

from privatelabbench.adapters.sklearn_adapter import RandomForestMoleculeAdapter
from privatelabbench.aggregate import summarize_sites
from privatelabbench.cli import main
from privatelabbench.eval.metrics import classification_metrics
from privatelabbench.eval.predictions import evaluate_prediction_table
from privatelabbench.federated.evaluator import evaluate_federated_directory
from privatelabbench.privacy.aggregation import aggregate_client_metrics
from privatelabbench.privacy.dp import PrivacyConfig
from privatelabbench.reports.receipt import verify_receipt
from privatelabbench.tasks.molecules import MoleculeDataset, load_molecule_csv


@pytest.mark.parametrize("negative", [-1.0, -0.8])
def test_negative_spearman_is_valid_site_evidence(negative):
    rows = [
        {"site": "a", "n_samples": 20, "estimate": negative},
        {"site": "b", "n_samples": 40, "estimate": 0.5},
    ]
    result = summarize_sites(rows, "spearman", disjoint=True)
    assert result["range"]["worst_sites"] == ["a"]
    assert result["range"]["absolute"] == pytest.approx(0.5 - negative)
    assert result["pooled"]["status"] == "not_poolable_from_site_metrics"


@pytest.mark.parametrize("estimate", [-1.01, 1.01])
def test_spearman_still_rejects_out_of_range_site_estimates(estimate):
    with pytest.raises(ValueError, match="mathematical range"):
        summarize_sites(
            [{"site": site, "n_samples": 20, "estimate": estimate} for site in "ab"],
            "spearman",
            disjoint=True,
        )


@pytest.mark.parametrize("label", [0, 1])
def test_single_class_molecule_model_returns_the_probability_of_class_one(
    tmp_path, label
):
    source = tmp_path / "single-class.csv"
    pd.DataFrame(
        {"smiles": ["C", "CC", "CCC", "CO"] * 5, "target": [label] * 20}
    ).to_csv(source, index=False)
    dataset = load_molecule_csv(str(source), target="target")
    result = RandomForestMoleculeAdapter(n_estimators=3).evaluate(dataset)
    assert result["task_type"] == "classification"
    assert result["metrics"]["accuracy"] == 1.0
    assert result["metrics"]["f1"] == float(label)
    assert math.isnan(result["metrics"]["auroc"])
    assert result["error_slices"]["error_rate"] == 0.0
    assert result["privacy_risk"]["train_loss_mean"] < 1e-5


@pytest.mark.parametrize("labels", [[0.1, 0.9], [1, 2], [-1, 1]])
def test_molecule_classification_rejects_labels_before_integer_truncation(
    tmp_path, labels
):
    source = tmp_path / "labels.csv"
    pd.DataFrame({"smiles": ["C", "CC"] * 10, "target": labels * 10}).to_csv(
        source, index=False
    )
    with pytest.raises(ValueError, match="binary"):
        load_molecule_csv(str(source), target="target", task_type="classification")
    dataset = MoleculeDataset(
        ["C", "CC"] * 10, np.array(labels * 10), "classification", "target"
    )
    with pytest.raises(ValueError, match="binary"):
        RandomForestMoleculeAdapter(n_estimators=3).evaluate(dataset)


@pytest.mark.parametrize("task_type", ["regression", "classification"])
def test_molecule_loader_rejects_nonfinite_targets(tmp_path, task_type):
    source = tmp_path / "nonfinite.csv"
    pd.DataFrame({"smiles": ["C", "CC"], "target": [0, np.inf]}).to_csv(
        source, index=False
    )
    with pytest.raises(ValueError, match="finite"):
        load_molecule_csv(str(source), target="target", task_type=task_type)


def test_zero_weight_clients_cannot_add_or_poison_metrics():
    assert aggregate_client_metrics(
        [{"mae": 1.0}, {"auroc": 0.5, "mae": float("nan")}], [1.0, 0.0]
    ) == {"mae": 1.0}


@pytest.mark.parametrize(
    "weights", [[-1, 2], [float("nan"), 1], [float("inf"), 1], [0, 0]]
)
def test_invalid_client_weights_are_rejected(weights):
    with pytest.raises(ValueError, match="weights"):
        aggregate_client_metrics([{"accuracy": 0.0}, {"accuracy": 1.0}], weights)


def test_large_weights_and_scores_do_not_overflow_a_finite_weighted_mean():
    assert aggregate_client_metrics([{"mae": 1.0}, {"mae": 3.0}], [1e308, 1e308]) == {
        "mae": 2.0
    }
    assert aggregate_client_metrics([{"mae": 1e308}, {"mae": 1e308}], [2, 2]) == {
        "mae": 1e308
    }


def test_missing_metrics_use_only_their_available_client_weights():
    assert aggregate_client_metrics(
        [{"mae": 1.0}, {"rmse": 3.0}, {"mae": 3.0}], [1, 100, 3]
    ) == {"mae": 2.5, "rmse": 3.0}


def test_metric_specific_weight_normalization_and_undefined_scores():
    assert aggregate_client_metrics([{"mae": 1.0}, {"rmse": 3.0}], [1e308, 1e-308]) == {
        "mae": 1.0,
        "rmse": 3.0,
    }
    assert math.isnan(
        aggregate_client_metrics([{"auroc": float("nan")}, {"auroc": 0.8}])["auroc"]
    )


def test_single_class_molecule_cli_writes_verifiable_local_reports(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.csv"
    pd.DataFrame({"smiles": ["C", "CC"] * 10, "target": [1] * 20}).to_csv(
        source, index=False
    )
    config = tmp_path / "evaluation.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "project": "single-class",
                "task": "molecules",
                "input": {"path": str(source), "target_column": "target"},
                "model": {"n_estimators": 3},
                "report": {
                    "json": str(tmp_path / "report.json"),
                    "markdown": str(tmp_path / "report.md"),
                    "manifest": str(tmp_path / "evaluation_manifest.json"),
                },
                "audit": {"path": str(tmp_path / "audit.jsonl")},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.argv", ["plb", "run", str(config)])
    assert main() == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["result"]["clean_metrics"]["accuracy"] == 1.0
    assert verify_receipt(tmp_path / "evaluation_receipt.json")["valid"]


def test_single_class_sites_have_defined_accuracy_and_undefined_auroc(tmp_path):
    for label in [0, 1]:
        pd.DataFrame({"smiles": ["C", "CC"] * 10, "target": [label] * 20}).to_csv(
            tmp_path / f"site-{label}.csv", index=False
        )
    result = evaluate_federated_directory(
        str(tmp_path),
        target="target",
        task_type="classification",
        privacy_config=PrivacyConfig(),
    )
    assert result["aggregate_clean_metrics"]["accuracy"] == 1.0
    assert math.isnan(result["aggregate_clean_metrics"]["auroc"])


@pytest.mark.parametrize("metrics", [["accuracy"], ["f1"], ["auroc"]])
def test_binary_metric_selection_cannot_hide_nonfinite_scores(metrics):
    with pytest.raises(ValueError, match="finite"):
        classification_metrics(
            np.array([0, 1]), np.array([np.nan, 0.8]), metric_names=metrics
        )
    with pytest.raises(ValueError, match="finite"):
        evaluate_prediction_table(
            pd.DataFrame({"target": [0, 1], "score": ["nan", "0.8"]}),
            target="target",
            prediction_column="score",
            task_type="classification",
            metric_names=metrics,
        )


@pytest.mark.parametrize(
    "targets,scores",
    [
        ([0.2, 1.0], [0.1, 0.9]),
        ([0, 1], [-0.1, 0.9]),
        ([0, 1], [0.1, 1.1]),
        ([0, 1], [[0.1], [0.9]]),
        ([], []),
        ([0, 1], [0.1]),
    ],
)
def test_binary_metrics_validate_labels_probabilities_and_alignment(targets, scores):
    with pytest.raises(ValueError):
        classification_metrics(
            np.asarray(targets), np.asarray(scores), metric_names=["accuracy"]
        )
