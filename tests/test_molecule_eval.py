from privatelabbench.models.sklearn_baseline import evaluate_random_forest
from privatelabbench.privacy.dp import PrivacyConfig, privatize_metrics
from privatelabbench.tasks.molecules import load_molecule_csv


def test_molecule_regression_eval_runs():
    dataset = load_molecule_csv("examples/molecules_demo.csv", target="label")
    result = evaluate_random_forest(dataset, seed=7)
    assert result["task_type"] == "regression"
    assert result["n_samples"] == 20
    assert "mae" in result["metrics"]


def test_dp_metric_reporting_changes_metric():
    clean = {"mae": 0.1}
    private = privatize_metrics(clean, PrivacyConfig(mode="dp", epsilon=1.0, seed=1))
    assert set(private) == {"mae"}
    assert private["mae"] != clean["mae"]
