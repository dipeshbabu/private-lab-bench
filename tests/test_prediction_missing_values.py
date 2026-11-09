import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from privatelabbench.design_audit import EvaluationDesign, prepare_evaluation
from privatelabbench.eval.predictions import (
    evaluate_prediction_csv,
    evaluate_prediction_table,
)

REPO = Path(__file__).resolve().parents[1]
TASKS = ("regression", "classification", "multiclass")
GUIDANCE = "explicit predeclared exclusions/eligibility before evaluation"


def table(task):
    frame = pd.DataFrame(
        {
            "sample_id": [f"sample-{i}" for i in range(6)],
            "split": ["train"] * 3 + ["test"] * 3,
            "qc": [True] * 6,
        }
    )
    if task == "regression":
        frame["target"] = np.arange(6, dtype=float)
        frame["prediction"] = frame["target"] + 0.1
    elif task == "classification":
        frame["target"] = ["negative", "positive"] * 3
        frame["prediction"] = [0.1, 0.9] * 3
    else:
        frame["target"] = ["low", "medium", "high"] * 2
        for label in ("low", "medium", "high"):
            frame[f"p_{label}"] = np.where(frame["target"] == label, 0.8, 0.1)
    return frame


def bindings(task, *, split=False):
    result = {"target": "target", "task_type": task, "require_sample_id": True}
    if task == "multiclass":
        result.update(
            prediction_columns=["p_low", "p_medium", "p_high"],
            class_labels=["low", "medium", "high"],
        )
    else:
        result["prediction_column"] = "prediction"
        if task == "classification":
            result["class_labels"] = ["negative", "positive"]
    if split:
        result["split_column"] = "split"
    return result


def prediction_column(task):
    return "p_medium" if task == "multiclass" else "prediction"


def cli_args(task):
    result = ["--target", "target", "--task-type", task]
    if task == "multiclass":
        result += [
            "--prediction-columns",
            "p_low",
            "p_medium",
            "p_high",
            "--class-labels",
            "low",
            "medium",
            "high",
        ]
    else:
        result += ["--prediction-column", "prediction"]
        if task == "classification":
            result += ["--class-labels", "negative", "positive"]
    return result


def cli(*args):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO)
    return subprocess.run(
        [sys.executable, "-m", "privatelabbench.cli", *map(str, args)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("role", ("target", "prediction", "split"))
@pytest.mark.parametrize("missing", (None, float("nan")), ids=("missing", "nan"))
@pytest.mark.parametrize("sampling_design", (False, True))
def test_api_rejects_missing_required_values_before_scoring(
    monkeypatch, task, role, missing, sampling_design
):
    frame = table(task)
    column = prediction_column(task) if role == "prediction" else role
    frame.loc[0, column] = missing
    before = frame.copy(deep=True)

    def must_not_score(*args, **kwargs):
        pytest.fail("Missing required values reached metric scoring")

    for metric in (
        "regression_metrics",
        "classification_metrics",
        "multiclass_metrics",
    ):
        monkeypatch.setattr(
            f"privatelabbench.eval.predictions.{metric}", must_not_score
        )
    options = bindings(task, split=role == "split")
    if sampling_design:
        options["sampling_design"] = {
            "schema_version": "sampling-design/v1",
            "unit": "sample",
            "method": "cluster_bootstrap",
            "cluster_columns": ["sample_id"],
            "min_independent_units": 2,
        }
    with pytest.raises(ValueError, match=GUIDANCE):
        evaluate_prediction_table(frame, **options)
    pd.testing.assert_frame_equal(frame, before)


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("role", ("target", "prediction", "split"))
@pytest.mark.parametrize("missing", ("", "NaN"), ids=("empty", "nan"))
def test_csv_api_and_actual_cli_reject_missing_values_without_reports(
    tmp_path, task, role, missing
):
    frame = table(task)
    column = prediction_column(task) if role == "prediction" else role
    frame[column] = frame[column].astype(object)
    frame.loc[0, column] = missing
    source = tmp_path / "predictions.csv"
    frame.to_csv(source, index=False)
    before = source.read_bytes()
    with pytest.raises(ValueError, match=GUIDANCE):
        evaluate_prediction_csv(str(source), **bindings(task, split=role == "split"))
    report = tmp_path / "evaluation.json"
    markdown = tmp_path / "evaluation.md"
    result = cli(
        "eval-predictions",
        source,
        *cli_args(task),
        *(["--split-column", "split"] if role == "split" else []),
        "--require-sample-id",
        "--json-report",
        report,
        "--report",
        markdown,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Evaluation rejected:" in result.stdout
    assert GUIDANCE in result.stdout
    assert "Traceback" not in result.stderr
    assert not report.exists() and not markdown.exists()
    assert not list(tmp_path.glob("*.shareable.json"))
    assert source.read_bytes() == before


@pytest.mark.parametrize("task", TASKS)
def test_valid_default_api_and_actual_cli_preserve_all_rows(tmp_path, task):
    import json

    frame = table(task)
    # Optional metadata missingness does not define eligibility or change the cohort.
    frame["qc"] = frame["qc"].astype(object)
    frame.loc[0, "qc"] = None
    frame.index = [10, 20, 30, 40, 50, 60]
    before_frame = frame.copy(deep=True)
    result = evaluate_prediction_table(frame, **bindings(task))
    assert result.n_samples == len(frame)
    pd.testing.assert_frame_equal(frame, before_frame)
    source = tmp_path / "predictions.csv"
    frame.to_csv(source, index=False)
    before = source.read_bytes()
    report = tmp_path / "evaluation.json"
    outcome = cli(
        "eval-predictions",
        source,
        *cli_args(task),
        "--require-sample-id",
        "--json-report",
        report,
        "--report",
        tmp_path / "evaluation.md",
    )
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr
    assert json.loads(report.read_text())["result"]["n_samples"] == len(frame)
    assert source.read_bytes() == before
    assert not list(tmp_path.glob("*.shareable.json"))


def runner_config(tmp_path, source, task):
    input_config = bindings(task)
    input_config["target_column"] = input_config.pop("target")
    input_config["path"] = str(source)
    return {
        "project": "synthetic-required-values",
        "task": "tabular",
        "benchmark": {
            "id": "synthetic-required-values",
            "version": "1",
            "suite": "synthetic",
            "domain": "tabular",
        },
        "input": input_config,
        "privacy": {"mode": "none"},
        "uncertainty": {"enabled": False},
        "report": {
            "json": str(tmp_path / "run.json"),
            "markdown": str(tmp_path / "run.md"),
            "manifest": str(tmp_path / "run_manifest.json"),
        },
        "audit": {"path": str(tmp_path / "run_audit.jsonl")},
        "release": {
            "schema_version": "release-policy/v1",
            "id": "reviewed-synthetic-required-values",
            "enabled": True,
            "min_samples": 2,
            "min_cell_size": 2,
            "require_privacy_audit": False,
        },
    }


@pytest.mark.parametrize("task", TASKS)
def test_predeclared_eligibility_filters_before_api_and_actual_cli_evaluation(
    tmp_path, task
):
    import json

    good = table(task)
    excluded = good.iloc[[0]].copy()
    excluded["sample_id"] = "predeclared-qc-failure"
    excluded["qc"] = False
    excluded["target"] = None
    for column in bindings(task).get("prediction_columns", ["prediction"]):
        excluded[column] = None
    source = tmp_path / "predictions.csv"
    pd.concat([good, excluded], ignore_index=True).to_csv(source, index=False)
    before = source.read_bytes()
    rules = EvaluationDesign.from_dict(
        {
            "schema_version": "evaluation-design/v1",
            "split_column": None,
            "exclusions": [{"column": "qc", "operator": "equals", "value": False}],
        }
    )
    prepared = prepare_evaluation(source, rules)
    assert prepared.artifact["audit"]["excluded_evaluation_records"] == 1
    assert prepared.frame["sample_id"].tolist() == good["sample_id"].tolist()
    result = evaluate_prediction_table(prepared.frame, **bindings(task))
    expected = evaluate_prediction_table(good, **bindings(task))
    assert result.n_samples == len(good)
    assert result.metrics == expected.metrics

    config = runner_config(tmp_path, source, task)
    config["evaluation_design"] = rules.as_dict()
    config_path = tmp_path / "evaluation.yaml"
    config_path.write_text(yaml.safe_dump(config))
    outcome = cli("run", config_path)
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr
    report = json.loads((tmp_path / "run.json").read_text())
    assert report["result"]["n_samples"] == len(good)
    assert report["result"]["clean_metrics"] == expected.metrics
    assert report["result"]["design_audit"]["excluded_evaluation_records"] == 1
    assert source.read_bytes() == before


@pytest.mark.parametrize("task", TASKS)
def test_rejected_actual_cli_rerun_invalidates_prior_shareable_results(tmp_path, task):
    frame = table(task)
    source = tmp_path / "predictions.csv"
    frame.to_csv(source, index=False)
    config_path = tmp_path / "evaluation.yaml"
    config_path.write_text(yaml.safe_dump(runner_config(tmp_path, source, task)))
    first = cli("run", config_path)
    assert first.returncode == 0, first.stdout + first.stderr
    public = tmp_path / "run_receipt.shareable.json"
    public_markdown = tmp_path / "run_receipt.md"
    assert public.exists() and public_markdown.exists()
    local_report = tmp_path / "run.json"
    prior_local_bytes = local_report.read_bytes()

    frame.loc[0, prediction_column(task)] = np.nan
    frame.to_csv(source, index=False)
    before_rejected_input = source.read_bytes()
    second = cli("run", config_path)
    assert second.returncode == 2, second.stdout + second.stderr
    assert GUIDANCE in second.stdout
    assert "Traceback" not in second.stderr
    assert not public.exists() and not public_markdown.exists()
    assert local_report.read_bytes() == prior_local_bytes
    assert source.read_bytes() == before_rejected_input


def test_empty_prediction_table_is_rejected_without_exclusion_fallback():
    with pytest.raises(ValueError, match="at least one evaluation row"):
        evaluate_prediction_table(
            table("regression").iloc[:0], **bindings("regression")
        )
