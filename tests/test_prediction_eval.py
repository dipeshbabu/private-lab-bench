import json

from privatelabbench.eval.predictions import evaluate_prediction_csv
from privatelabbench.privacy.dp import PrivacyConfig, privatize_metrics
from privatelabbench.reports.json import write_json_report


def test_prediction_eval_runs():
    result = evaluate_prediction_csv(
        "examples/predictions_demo.csv",
        target="label",
        prediction_column="pred",
    )
    assert result.task_type == "regression"
    assert result.n_samples == 20
    assert "mae" in result.metrics
    assert "prediction_mean" in result.prediction_summary


def test_prediction_json_report(tmp_path):
    result = evaluate_prediction_csv(
        "examples/predictions_demo.csv",
        target="label",
        prediction_column="pred",
    )
    privacy_config = PrivacyConfig(mode="dp", epsilon=8.0, seed=1)
    reported = privatize_metrics(result.metrics, privacy_config)
    output = tmp_path / "prediction_report.json"
    write_json_report(
        str(output),
        report_type="prediction_evaluation",
        result={"clean_metrics": result.metrics, "reported_metrics": reported},
        privacy_config=privacy_config,
    )
    payload = json.loads(output.read_text())
    assert payload["report_type"] == "prediction_evaluation"
    assert payload["privacy"]["mode"] == "dp"
    assert "run_id" in payload
