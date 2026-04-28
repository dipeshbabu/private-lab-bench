from privatelabbench.federated.evaluator import discover_client_csvs, evaluate_federated_directory
from privatelabbench.privacy.dp import PrivacyConfig


def test_discover_client_csvs():
    files = discover_client_csvs("examples/labs")
    assert len(files) == 3
    assert [path.name for path in files] == ["lab_a.csv", "lab_b.csv", "lab_c.csv"]


def test_federated_eval_runs():
    result = evaluate_federated_directory(
        "examples/labs",
        target="label",
        privacy_config=PrivacyConfig(mode="dp", epsilon=8.0, seed=7),
        seed=7,
    )
    assert result["n_clients"] == 3
    assert result["total_samples"] == 60
    assert len(result["clients"]) == 3
    assert "mae" in result["aggregate_clean_metrics"]
    assert "mae" in result["aggregate_reported_metrics"]
