import json

import pytest

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
    assert result.privacy_risk is None


def test_prediction_eval_membership_risk_with_split_column(tmp_path):
    csv_path = tmp_path / "predictions_with_split.csv"
    csv_path.write_text(
        "\n".join(
            [
                "label,pred,split",
                "0.10,0.10,train",
                "0.20,0.21,train",
                "0.80,0.78,member",
                "0.90,0.88,1",
                "0.10,0.45,test",
                "0.20,0.52,holdout",
                "0.80,0.51,nonmember",
                "0.90,0.48,0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = evaluate_prediction_csv(
        str(csv_path),
        target="label",
        prediction_column="pred",
        task_type="regression",
        split_column="split",
    )

    assert result.split_column == "split"
    assert result.privacy_risk is not None
    assert result.privacy_risk["risk_level"] in {"moderate", "high"}
    assert result.privacy_risk["member_advantage"] > 0
    assert result.privacy_risk["n_member"] == 4
    assert result.privacy_risk["n_nonmember"] == 4


def test_prediction_eval_rejects_unknown_split_value(tmp_path):
    csv_path = tmp_path / "predictions_with_bad_split.csv"
    csv_path.write_text("label,pred,split\n0.1,0.1,train\n0.2,0.3,shadow\n", encoding="utf-8")

    with pytest.raises(ValueError, match="split_column values"):
        evaluate_prediction_csv(
            str(csv_path),
            target="label",
            prediction_column="pred",
            task_type="regression",
            split_column="split",
        )


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
