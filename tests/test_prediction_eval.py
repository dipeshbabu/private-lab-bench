import json

import pytest

from privatelabbench.eval.predictions import evaluate_prediction_csv
from privatelabbench.privacy.dp import PrivacyConfig, privatize_metrics
from privatelabbench.reports.json import write_json_report


def test_prediction_eval_runs_with_schema_and_slices():
    result = evaluate_prediction_csv(
        "examples/predictions_demo.csv",
        target="label",
        prediction_column="pred",
        sample_id_column="sample_id",
        require_sample_id=True,
        slice_columns=["series"],
        min_slice_size=2,
    )
    assert result.task_type == "regression"
    assert result.n_samples == 20
    assert result.schema.as_dict()["schema_version"] == "prediction-table/v1"
    assert result.sample_id_status == "present"
    assert "series" in result.schema.metadata_columns
    assert result.schema.slice_columns == ("series",)
    assert result.slice_metrics["series"]["aliphatic"]["status"] == "evaluated"
    assert "mae" in result.slice_metrics["series"]["aliphatic"]["metrics"]


def test_binary_classification_supports_string_labels(tmp_path):
    csv_path = tmp_path / "binary.csv"
    csv_path.write_text(
        "sample_id,target,score,site\n"
        "a,negative,0.10,north\n"
        "b,positive,0.90,north\n"
        "c,negative,0.20,south\n"
        "d,positive,0.80,south\n",
        encoding="utf-8",
    )
    result = evaluate_prediction_csv(
        str(csv_path),
        target="target",
        prediction_column="score",
        task_type="classification",
        class_labels=["negative", "positive"],
        require_sample_id=True,
        slice_columns=["site"],
    )
    assert result.class_labels == ("negative", "positive")
    assert result.metrics["accuracy"] == 1.0
    assert result.metrics["f1"] == 1.0
    assert result.slice_metrics["site"]["north"]["n"] == 2


def test_multiclass_prediction_table_runs():
    result = evaluate_prediction_csv(
        "examples/multiclass_predictions_demo.csv",
        target="target",
        prediction_columns=["p_alpha", "p_beta", "p_gamma"],
        task_type="multiclass",
        class_labels=["alpha", "beta", "gamma"],
        require_sample_id=True,
        slice_columns=["site"],
        min_slice_size=2,
    )
    assert result.task_type == "multiclass"
    assert result.prediction_column is None
    assert result.prediction_columns == ("p_alpha", "p_beta", "p_gamma")
    assert result.metrics["accuracy"] == 1.0
    assert "macro_f1" in result.metrics
    assert "log_loss" in result.metrics
    assert result.slice_metrics["site"]["north"]["status"] == "evaluated"


def test_multiclass_rejects_probabilities_that_do_not_sum_to_one(tmp_path):
    csv_path = tmp_path / "bad_multiclass.csv"
    csv_path.write_text(
        "sample_id,target,p_a,p_b,p_c\n"
        "a,a,0.8,0.4,0.1\n"
        "b,b,0.1,0.8,0.1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="sum to 1.0"):
        evaluate_prediction_csv(
            str(csv_path),
            target="target",
            prediction_columns=["p_a", "p_b", "p_c"],
            task_type="multiclass",
            class_labels=["a", "b", "c"],
        )


def test_prediction_table_rejects_duplicate_sample_ids(tmp_path):
    csv_path = tmp_path / "duplicates.csv"
    csv_path.write_text(
        "sample_id,target,prediction\n"
        "same,0.1,0.1\n"
        "same,0.2,0.2\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must be unique"):
        evaluate_prediction_csv(
            str(csv_path),
            target="target",
            prediction_column="prediction",
            task_type="regression",
            require_sample_id=True,
        )


def test_missing_sample_id_can_be_explicitly_optional(tmp_path):
    csv_path = tmp_path / "legacy.csv"
    csv_path.write_text("target,prediction\n0.1,0.1\n0.2,0.2\n", encoding="utf-8")
    result = evaluate_prediction_csv(
        str(csv_path),
        target="target",
        prediction_column="prediction",
        task_type="regression",
        require_sample_id=False,
    )
    assert result.sample_id_status == "missing"


def test_slice_metrics_suppress_small_groups(tmp_path):
    csv_path = tmp_path / "slices.csv"
    csv_path.write_text(
        "sample_id,target,prediction,site\n"
        "a,0.1,0.1,north\n"
        "b,0.2,0.2,north\n"
        "c,0.3,0.3,south\n",
        encoding="utf-8",
    )
    result = evaluate_prediction_csv(
        str(csv_path),
        target="target",
        prediction_column="prediction",
        task_type="regression",
        slice_columns=["site"],
        min_slice_size=2,
        require_sample_id=True,
    )
    assert result.slice_metrics["site"]["north"]["status"] == "evaluated"
    assert result.slice_metrics["site"]["south"] == {"n": 1, "status": "skipped_min_slice_size"}


def test_prediction_eval_membership_risk_with_split_column(tmp_path):
    csv_path = tmp_path / "predictions_with_split.csv"
    csv_path.write_text(
        "\n".join(
            [
                "sample_id,label,pred,split",
                "a,0.10,0.10,train",
                "b,0.20,0.21,train",
                "c,0.80,0.78,member",
                "d,0.90,0.88,1",
                "e,0.10,0.45,test",
                "f,0.20,0.52,holdout",
                "g,0.80,0.51,nonmember",
                "h,0.90,0.48,0",
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
        require_sample_id=True,
    )
    assert result.split_column == "split"
    assert result.privacy_risk is not None
    assert result.privacy_risk["risk_level"] in {"moderate", "high"}
    assert result.privacy_risk["member_advantage"] > 0
    assert result.privacy_risk["n_member"] == 4
    assert result.privacy_risk["n_nonmember"] == 4


def test_prediction_eval_rejects_unknown_split_value(tmp_path):
    csv_path = tmp_path / "predictions_with_bad_split.csv"
    csv_path.write_text(
        "sample_id,label,pred,split\na,0.1,0.1,train\nb,0.2,0.3,shadow\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="split_column values"):
        evaluate_prediction_csv(
            str(csv_path),
            target="label",
            prediction_column="pred",
            task_type="regression",
            split_column="split",
        )


def test_prediction_json_report_includes_schema_and_aggregates_only(tmp_path):
    result = evaluate_prediction_csv(
        "examples/tabular_predictions_demo.csv",
        target="target",
        prediction_column="prediction",
        slice_columns=["site"],
        require_sample_id=True,
    )
    privacy_config = PrivacyConfig(mode="dp", epsilon=8.0, seed=1)
    reported = privatize_metrics(result.metrics, privacy_config)
    output = tmp_path / "prediction_report.json"
    write_json_report(
        str(output),
        report_type="prediction_evaluation",
        result={
            "prediction_table_schema": result.schema.as_dict(),
            "clean_metrics": result.metrics,
            "reported_metrics": reported,
            "slice_metrics": result.slice_metrics,
            "sharing_boundary": {"row_level_values_included": False},
        },
        privacy_config=privacy_config,
    )
    payload = json.loads(output.read_text())
    serialized = json.dumps(payload)
    assert payload["report_type"] == "prediction_evaluation"
    assert payload["result"]["prediction_table_schema"]["schema_version"] == "prediction-table/v1"
    assert payload["result"]["sharing_boundary"]["row_level_values_included"] is False
    assert "s01" not in serialized
