import os
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from privatelabbench.cli import main
from privatelabbench.eval.paired_comparison import (
    PairedComparisonConfig,
    compare_prediction_tables,
)
from privatelabbench.eval.predictions import evaluate_prediction_table
from privatelabbench.runner import run_config
from privatelabbench.validation import validate_config


@pytest.mark.parametrize(
    "command,output_flag",
    [
        ("eval-predictions", "--report"),
        ("eval-predictions", "--json-report"),
        ("eval-molecules", "--report"),
        ("eval-federated", "--report"),
    ],
)
def test_legacy_evaluation_preserves_input_csv(
    tmp_path, monkeypatch, command, output_flag
):
    source = tmp_path / "data.csv"
    example = (
        "predictions_demo.csv"
        if command == "eval-predictions"
        else "molecules_demo.csv"
    )
    shutil.copyfile(Path("examples") / example, source)
    original = source.read_bytes()
    args = [
        "plb",
        command,
        str(tmp_path if command == "eval-federated" else source),
        "--target",
        "label",
        output_flag,
        str(source),
    ]
    if command == "eval-predictions":
        args.extend(["--prediction-column", "pred"])
        args.extend(
            [
                "--json-report" if output_flag == "--report" else "--report",
                str(tmp_path / "separate-report.txt"),
            ]
        )
    monkeypatch.setattr("sys.argv", args)
    assert main() == 2
    assert source.read_bytes() == original
    assert not (tmp_path / "separate-report.txt").exists()


def test_legacy_prediction_reports_cannot_overwrite_each_other(tmp_path, monkeypatch):
    source = tmp_path / "data.csv"
    shutil.copyfile("examples/predictions_demo.csv", source)
    output = tmp_path / "report.json"
    output.write_text("previous report", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "plb",
            "eval-predictions",
            str(source),
            "--target",
            "label",
            "--prediction-column",
            "pred",
            "--report",
            str(output),
            "--json-report",
            str(output),
        ],
    )
    assert main() == 2
    assert output.read_text(encoding="utf-8") == "previous report"


@pytest.mark.parametrize("api", ["evaluate", "compare"])
@pytest.mark.parametrize(
    "changes",
    [
        {"prediction_column": "target"},
        {"prediction_column": "sample_id"},
        {"sample_id_column": "target"},
    ],
)
def test_prediction_column_roles_must_be_distinct(api, changes):
    frame = pd.DataFrame(
        {
            "sample_id": ["1", "2", "3"],
            "target": [1.0, 2.0, 3.0],
            "prediction": [1.1, 2.2, 2.8],
        }
    )
    args = {
        "target": "target",
        "prediction_column": "prediction",
        "sample_id_column": "sample_id",
        "task_type": "regression",
        **changes,
    }
    with pytest.raises(ValueError, match="distinct columns"):
        if api == "evaluate":
            evaluate_prediction_table(frame, **args)
        else:
            compare_prediction_tables(
                "unused-a", "unused-b", frame_a=frame, frame_b=frame, **args
            )


def test_validation_and_runner_resolve_the_same_config_input(tmp_path, monkeypatch):
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    source = definitions / "data.csv"
    source.write_text(
        "sample_id,target,prediction\na,1,1.1\nb,2,2.2\nc,3,2.8\n", encoding="utf-8"
    )
    shadow = tmp_path / "data.csv"
    shadow.write_text("unrelated_column\nprivate-data\n", encoding="utf-8")
    config = definitions / "evaluation.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "task": "predictions",
                "project": "path-test",
                "input": {
                    "path": "data.csv",
                    "target_column": "target",
                    "prediction_column": "prediction",
                    "task_type": "regression",
                },
                "report": {
                    "json": str(tmp_path / "report.json"),
                    "markdown": str(tmp_path / "report.md"),
                    "manifest": str(tmp_path / "run_manifest.json"),
                    "audit": str(tmp_path / "audit.jsonl"),
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    result = validate_config(str(config))
    assert result.valid, result.errors
    summary = run_config(str(config))
    assert summary["n_samples"] == 3
    assert summary["clean_metrics"]["mae"] == pytest.approx(1 / 6)
    assert shadow.read_text(encoding="utf-8") == "unrelated_column\nprivate-data\n"


@pytest.mark.parametrize("api", ["evaluate", "compare"])
def test_missing_and_literal_slice_labels_cannot_silently_collapse(api):
    frame = pd.DataFrame(
        {
            "sample_id": ["a", "b", "c", "d"],
            "target": [1.0, 2.0, 3.0, 4.0],
            "prediction": [1.0, 2.0, 13.0, 14.0],
            "site": [None, None, "<NA>", "<NA>"],
        }
    )
    args = {
        "target": "target",
        "prediction_column": "prediction",
        "task_type": "regression",
        "slice_columns": ["site"],
    }
    with pytest.raises(ValueError, match="ambiguous slice"):
        if api == "evaluate":
            evaluate_prediction_table(frame, **args)
        else:
            compare_prediction_tables(
                "unused-a", "unused-b", frame_a=frame, frame_b=frame, **args
            )


@pytest.mark.parametrize(
    "command", ["eval-predictions", "eval-molecules", "eval-federated"]
)
def test_legacy_evaluation_still_writes_separate_reports(
    tmp_path, monkeypatch, command
):
    source = tmp_path / "data.csv"
    example = (
        "predictions_demo.csv"
        if command == "eval-predictions"
        else "molecules_demo.csv"
    )
    shutil.copyfile(Path("examples") / example, source)
    original = source.read_bytes()
    output = tmp_path / "report.md"
    args = [
        "plb",
        command,
        str(tmp_path if command == "eval-federated" else source),
        "--target",
        "label",
        "--report",
        str(output),
    ]
    if command == "eval-predictions":
        args.extend(
            [
                "--prediction-column",
                "pred",
                "--json-report",
                str(tmp_path / "report.json"),
            ]
        )
    monkeypatch.setattr("sys.argv", args)
    assert main() == 0
    assert output.read_text(encoding="utf-8").startswith("#")
    assert source.read_bytes() == original


def test_legacy_prediction_report_rejects_hard_link_to_input(tmp_path, monkeypatch):
    source = tmp_path / "data.csv"
    shutil.copyfile("examples/predictions_demo.csv", source)
    original = source.read_bytes()
    alias = tmp_path / "report.json"
    try:
        os.link(source, alias)
    except OSError:
        pytest.skip("Hard links are unavailable on this filesystem")
    monkeypatch.setattr(
        "sys.argv",
        [
            "plb",
            "eval-predictions",
            str(source),
            "--target",
            "label",
            "--prediction-column",
            "pred",
            "--report",
            str(tmp_path / "report.md"),
            "--json-report",
            str(alias),
        ],
    )
    assert main() == 2
    assert source.read_bytes() == alias.read_bytes() == original
    assert not (tmp_path / "report.md").exists()


def test_slice_labels_cannot_collapse_distinct_numeric_and_text_categories():
    frame = pd.DataFrame(
        {
            "target": [1.0, 2.0, 3.0, 4.0],
            "prediction": [1.0, 2.0, 13.0, 14.0],
            "site": [1, 1, "1", "1"],
        }
    )
    with pytest.raises(ValueError, match="ambiguous slice"):
        evaluate_prediction_table(
            frame,
            target="target",
            prediction_column="prediction",
            task_type="regression",
            slice_columns=["site"],
        )


def test_nonconflicting_missing_slice_keeps_all_observations():
    frame = pd.DataFrame(
        {
            "target": [1.0, 2.0, 3.0, 4.0],
            "prediction": [1.0, 2.0, 13.0, 14.0],
            "site": [None, None, "named", "named"],
        }
    )
    result = evaluate_prediction_table(
        frame,
        target="target",
        prediction_column="prediction",
        task_type="regression",
        slice_columns=["site"],
    )
    groups = result.slice_metrics["site"]
    assert sum(group["n"] for group in groups.values()) == result.n_samples == 4
    assert groups["<NA>"]["metrics"]["mae"] == 0
    assert groups["named"]["metrics"]["mae"] == 10


@pytest.mark.parametrize("task", ["regression", "classification", "multiclass"])
def test_metrics_and_paired_evidence_survive_table_reordering(task):
    rng = np.random.default_rng(17)
    n = 12
    frame = pd.DataFrame(
        {"sample_id": [f"s{i:02}" for i in range(n)], "site": ["a", "b"] * (n // 2)}
    )
    args = {"target": "target", "task_type": task, "slice_columns": ["site"]}
    if task == "regression":
        frame["target"] = rng.normal(size=n)
        frame["prediction"] = frame["target"] + rng.normal(0, 0.2, size=n)
        prediction_columns = ["prediction"]
        args["prediction_column"] = "prediction"
    elif task == "classification":
        frame["target"] = ["01", "02"] * (n // 2)
        frame["prediction"] = rng.uniform(0.1, 0.9, size=n)
        prediction_columns = ["prediction"]
        args.update(prediction_column="prediction", class_labels=["01", "02"])
    else:
        frame["target"] = ["01", "02", "03"] * (n // 3)
        values = rng.uniform(0.1, 1, size=(n, 3))
        prediction_columns = ["p1", "p2", "p3"]
        frame[prediction_columns] = values / values.sum(axis=1, keepdims=True)
        args.update(
            prediction_column=None,
            prediction_columns=prediction_columns,
            class_labels=["01", "02", "03"],
        )
    evaluated = evaluate_prediction_table(frame, **args)
    reordered = evaluate_prediction_table(frame.sample(frac=1, random_state=3), **args)
    assert reordered.metrics == pytest.approx(evaluated.metrics)
    for groups in reordered.slice_metrics.values():
        assert sum(group["n"] for group in groups.values()) == n
    other = frame.copy()
    other[prediction_columns] = other[prediction_columns].iloc[::-1].to_numpy()
    config = PairedComparisonConfig(resamples=100, permutations=0, min_samples=2)
    expected = compare_prediction_tables(
        "a", "b", frame_a=frame, frame_b=other, config=config, **args
    )
    actual = compare_prediction_tables(
        "a",
        "b",
        frame_a=frame,
        frame_b=other.sample(frac=1, random_state=7),
        config=config,
        **args,
    )
    assert actual == expected
