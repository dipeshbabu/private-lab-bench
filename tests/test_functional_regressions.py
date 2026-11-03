"""Regressions for scientific alignment and preservation of caller inputs."""

import pandas as pd
import pytest
import yaml

from privatelabbench.cli import main
from privatelabbench.eval.paired_comparison import compare_prediction_tables
from privatelabbench.eval.predictions import evaluate_prediction_table
from privatelabbench.runner import run_config


@pytest.mark.parametrize("target,changed", [(100000.0, 100001.0), (1.0, 1.0000001)])
def test_paired_comparison_rejects_nearby_but_different_targets(
    tmp_path, target, changed
):
    a = pd.DataFrame(
        {
            "sample_id": ["s1", "s2"],
            "target": [target, 2.0],
            "prediction": [target, 2.0],
        }
    )
    b = a.copy()
    b.loc[0, "target"] = changed
    paths = [tmp_path / "a.csv", tmp_path / "b.csv"]
    for path, frame in zip(paths, (a, b)):
        frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="Targets disagree"):
        compare_prediction_tables(
            *map(str, paths), target="target", task_type="regression"
        )


@pytest.mark.parametrize("column", ["target", "site"])
def test_paired_comparison_preserves_numeric_looking_labels(tmp_path, column):
    a = pd.DataFrame(
        {
            "sample_id": ["s1", "s2"],
            "target": ["001", "1"],
            "prediction": [0.1, 0.9],
            "site": ["001", "001"],
        }
    )
    b = a.copy()
    b.loc[0, column] = "1"
    paths = [tmp_path / "a.csv", tmp_path / "b.csv"]
    for path, frame in zip(paths, (a, b)):
        frame.to_csv(path, index=False)
    with pytest.raises(
        ValueError,
        match="Targets disagree" if column == "target" else "metadata.*disagrees",
    ):
        compare_prediction_tables(
            *map(str, paths),
            target="target",
            task_type="classification",
            class_labels=["001", "1"],
            slice_columns=["site"],
        )


def test_two_probability_columns_have_defined_auc_and_uncertainty():
    frame = pd.DataFrame(
        {
            "sample_id": [f"s{i}" for i in range(40)],
            "target": ["yes", "no"] * 20,
            "p_yes": [0.9, 0.2] * 20,
            "p_no": [0.1, 0.8] * 20,
        }
    )
    from privatelabbench.eval.uncertainty import BootstrapConfig

    result = evaluate_prediction_table(
        frame,
        target="target",
        prediction_columns=["p_yes", "p_no"],
        task_type="multiclass",
        class_labels=["yes", "no"],
        uncertainty_config=BootstrapConfig(enabled=True, resamples=100),
    )
    assert result.metrics["macro_auroc_ovr"] == pytest.approx(1.0)
    interval = result.uncertainty["metrics"]["macro_auroc_ovr"]
    assert interval["status"] == "evaluated"
    assert interval["lower"] == interval["upper"] == pytest.approx(1.0)


def test_paired_cluster_identifiers_must_match_exactly(tmp_path):
    a = pd.DataFrame(
        {
            "sample_id": ["s1", "s2"],
            "target": [0.1, 0.2],
            "prediction": [0.2, 0.3],
            "patient": ["001", "1"],
        }
    )
    b = a.copy()
    b.loc[0, "patient"] = "1"
    paths = [tmp_path / "a.csv", tmp_path / "b.csv"]
    for path, frame in zip(paths, (a, b)):
        frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="metadata.*disagrees"):
        compare_prediction_tables(
            *map(str, paths),
            target="target",
            task_type="regression",
            sampling_design={
                "schema_version": "sampling-design/v1",
                "unit": "patient",
                "method": "cluster_bootstrap",
                "cluster_columns": ["patient"],
                "min_independent_units": 2,
            },
        )


@pytest.mark.parametrize(
    "source_kind", ["config", "protocol", "design", "reference", "training_reference"]
)
def test_runner_preserves_non_table_inputs_before_invalidating_exports(
    tmp_path, source_kind
):
    data = tmp_path / "data.csv"
    data.write_text(
        "sample_id,target,prediction\na,0.1,0.2\nb,0.3,0.4\n", encoding="utf-8"
    )
    output = tmp_path / "run_receipt.shareable.json"
    output.write_text("old approved export", encoding="utf-8")
    config = {
        "task": "predictions",
        "input": {
            "path": str(data),
            "target_column": "target",
            "prediction_column": "prediction",
            "task_type": "regression",
        },
        "report": {
            "json": str(tmp_path / "run.json"),
            "markdown": str(tmp_path / "run.md"),
            "manifest": str(tmp_path / "run_manifest.json"),
        },
    }
    path = tmp_path / "config.yaml"
    source = path if source_kind == "config" else tmp_path / (source_kind + ".yaml")
    if source_kind == "protocol":
        from privatelabbench.protocols import resolve_protocol

        source.write_text(
            yaml.safe_dump(
                resolve_protocol("plb://generic/regression@1.0.0").as_dict()
            ),
            encoding="utf-8",
        )
        config["protocol"] = source.name
    elif source_kind == "design":
        source.write_text(
            yaml.safe_dump(
                {
                    "schema_version": "evaluation-design/v1",
                    "unit": "sample",
                    "label_column": "target",
                }
            ),
            encoding="utf-8",
        )
        config["evaluation_design"] = source.name
    elif source_kind in {"reference", "training_reference"}:
        source.write_bytes(data.read_bytes())
        config["diagnostics" if source_kind == "reference" else "design_audit"] = {
            (
                "reference_path" if source_kind == "reference" else "training_reference"
            ): str(source)
        }
    config["report"]["json"] = str(source)
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    original = source.read_bytes()
    with pytest.raises(ValueError, match="separate"):
        run_config(str(path))
    assert source.read_bytes() == original
    assert output.read_text(encoding="utf-8") == "old approved export"


@pytest.mark.parametrize(
    "kind", ["json", "markdown", "manifest", "audit", "public_receipt"]
)
def test_runner_rejects_outputs_that_replace_input_tables(tmp_path, kind):
    data = tmp_path / (
        "run_receipt.shareable.json" if kind == "public_receipt" else "data.csv"
    )
    data.write_text(
        "sample_id,target,prediction\na,0.1,0.2\nb,0.3,0.4\n", encoding="utf-8"
    )
    config = {
        "task": "predictions",
        "input": {
            "path": str(data),
            "target_column": "target",
            "prediction_column": "prediction",
            "task_type": "regression",
        },
        "report": {
            "json": str(tmp_path / "run.json"),
            "markdown": str(tmp_path / "run.md"),
            "manifest": str(tmp_path / "run_manifest.json"),
        },
        "audit": {"path": str(tmp_path / "audit.jsonl")},
    }
    if kind == "audit":
        config["audit"]["path"] = str(data)
    elif kind != "public_receipt":
        config["report"][kind] = str(data)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    original = data.read_bytes()
    with pytest.raises(ValueError, match="separate|collid|overlap"):
        run_config(str(path))
    assert data.read_bytes() == original
    assert not (tmp_path / "run.json").exists()


@pytest.mark.parametrize(
    "command,protected",
    [
        ("gate", "policy"),
        ("gate", "trust_store"),
        ("sign", "policy"),
        ("sign", "private_key"),
    ],
)
def test_cli_rejects_output_collisions_before_removing_inputs(
    tmp_path, monkeypatch, command, protected
):
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}", encoding="utf-8")
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "schema_version: release-policy/v1\nid: original-policy\n", encoding="utf-8"
    )
    private_key = tmp_path / "key.pem"
    private_key.write_text("private test material", encoding="utf-8")
    trust_store = tmp_path / "trust.yaml"
    trust_store.write_text(
        "schema_version: receipt-trust-store/v1\nkeys: {}\n", encoding="utf-8"
    )
    files = {"policy": policy, "private_key": private_key, "trust_store": trust_store}
    original = {path: path.read_bytes() for path in (artifact, *files.values())}
    args = [
        "plb",
        command,
        str(artifact),
        "--policy",
        str(policy),
        "--out",
        str(files[protected]),
    ]
    args += (
        ["--trust-store", str(trust_store)]
        if command == "gate"
        else [
            "--private-key",
            str(private_key),
            "--signer-id",
            "example",
            "--key-id",
            "example-v1",
        ]
    )
    monkeypatch.setattr("sys.argv", args)
    try:
        result = main()
    except ValueError as exc:
        assert "separate" in str(exc) or "preserve" in str(exc)
    else:
        assert result == 2
    assert {path: path.read_bytes() for path in original} == original


@pytest.mark.parametrize("command", ["aggregate", "compare"])
def test_evidence_commands_preserve_policy_files(tmp_path, monkeypatch, command):
    policy = tmp_path / "policy.yaml"
    policy.write_text("id: preserve-this-policy\n", encoding="utf-8")
    originals = policy.read_bytes()
    source = tmp_path / "input.json"
    source.write_text("{}", encoding="utf-8")
    args = ["plb", command, str(source), "--release-policy", str(policy)]
    args += (
        ["--out", str(policy)] if command == "aggregate" else ["--report", str(policy)]
    )
    monkeypatch.setattr("sys.argv", args)
    with pytest.raises(ValueError, match="separate"):
        main()
    assert policy.read_bytes() == originals


def test_runner_rejects_report_aliases_and_hardlinked_inputs(tmp_path):
    import os
    from privatelabbench.core.local_io import validate_output_paths

    source = tmp_path / "data.csv"
    source.write_text("original input", encoding="utf-8")
    output = tmp_path / "report.json"
    with pytest.raises(ValueError, match="separate"):
        validate_output_paths([source], [output, output])
    try:
        os.link(source, output)
    except OSError:
        pytest.skip("Hard links are unavailable on this filesystem")
    with pytest.raises(ValueError, match="separate"):
        validate_output_paths([source], [output])
    assert source.read_text(encoding="utf-8") == "original input"
