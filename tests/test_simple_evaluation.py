import json

import pytest
import yaml

from privatelabbench.cli import main
from privatelabbench.evaluate import prediction_bindings
from privatelabbench.reports.receipt import verify_receipt


def table(tmp_path, *, targets=None, extra="", extra_row=""):
    path = tmp_path / "predictions.csv"
    targets = targets if targets is not None else [i + 0.123456789 for i in range(24)]
    path.write_text(
        "sample_id,target,prediction"
        + extra
        + "\n"
        + "".join(
            f"private-sample-{i},{target},{target + 0.1}{extra_row}\n"
            for i, target in enumerate(targets)
        )
    )
    return path


def invoke(monkeypatch, args):
    monkeypatch.setattr("sys.argv", ["plb", *map(str, args)])
    return main()


def test_evaluate_conventional_table_writes_verified_local_receipt_and_concise_summary(
    tmp_path, monkeypatch, capsys
):
    path = table(tmp_path)
    output = tmp_path / "results"
    assert (
        invoke(
            monkeypatch,
            ["evaluate", path, "--output-dir", output, "--resamples", "100"],
        )
        == 0
    )
    receipt = output / "evaluation_receipt.json"
    assert verify_receipt(receipt)["valid"]
    assert not (output / "evaluation_receipt.shareable.json").exists()
    summary = capsys.readouterr().out
    assert (
        "Samples" in summary
        and "24" in summary
        and "RMSE" in summary
        and "95% CI" in summary
    )
    assert "local only; no release policy" in summary and str(receipt) in summary
    assert "private-sample" not in summary and len(summary.splitlines()) < 15


def test_init_copies_settings_and_local_path_but_no_dataset_rows(tmp_path, monkeypatch):
    path = table(tmp_path)
    output = tmp_path / "results"
    config = tmp_path / "evaluation.yaml"
    args = ["init", path, "--out", config, "--output-dir", output, "--resamples", "100"]
    assert invoke(monkeypatch, args) == 0
    text = config.read_text()
    assert (
        str(path) in text and "private-sample" not in text and "0.123456789" not in text
    )
    assert not output.exists()
    assert invoke(monkeypatch, args) == 2
    assert invoke(monkeypatch, [*args, "--force"]) == 0
    assert invoke(monkeypatch, ["run", config]) == 0
    assert verify_receipt(output / "evaluation_receipt.json")["valid"]


def test_binary_type_and_named_positive_class_require_explicit_choices(
    tmp_path, monkeypatch, capsys
):
    path = tmp_path / "binary.csv"
    path.write_text("sample_id,target,prediction\na,1,0.9\nb,0,0.1\nc,1,0.8\nd,0,0.2\n")
    output = tmp_path / "results"
    args = ["evaluate", path, "--output-dir", output]
    assert invoke(monkeypatch, args) == 2
    assert "--task-type" in capsys.readouterr().out
    assert invoke(monkeypatch, [*args, "--task-type", "classification"]) == 0
    summary = capsys.readouterr().out
    assert (
        "Positive class       1" in summary
        and "AUROC" in summary
        and "skipped_min_samples" in summary
    )
    path.write_text(
        "sample_id,target,prediction\na,diseased,0.9\nb,healthy,0.1\nc,diseased,0.8\nd,healthy,0.2\n"
    )
    assert invoke(monkeypatch, [*args, "--task-type", "classification"]) == 2
    assert "--class-labels" in capsys.readouterr().out
    assert invoke(monkeypatch, [*args, "--class-labels", "healthy", "diseased"]) == 0
    receipt = json.loads((output / "evaluation_receipt.json").read_text())
    assert receipt["local"]["exact_metrics"]["auroc"] == 1


@pytest.mark.parametrize(
    "kind",
    [
        "target_alias",
        "prediction_alias",
        "missing_id",
        "duplicate_header",
        "integer_target",
    ],
)
def test_ambiguous_or_incomplete_tables_do_not_guess(kind, tmp_path):
    path = table(tmp_path)
    text = path.read_text()
    if kind == "target_alias":
        path = table(tmp_path, extra=",label", extra_row=",0")
    if kind == "prediction_alias":
        path = table(tmp_path, extra=",pred", extra_row=",0.2")
    if kind == "missing_id":
        path.write_text(text.replace("sample_id", "internal_id"))
    if kind == "duplicate_header":
        path.write_text(text.replace("sample_id,target", "target,target"))
    if kind == "integer_target":
        path = table(tmp_path, targets=list(range(24)))
    with pytest.raises(ValueError):
        prediction_bindings(path)


def test_repeated_slices_baseline_and_small_slice_status(tmp_path, monkeypatch, capsys):
    path = table(tmp_path, extra=",site,baseline", extra_row=",lab-a,0")
    output = tmp_path / "results"
    assert (
        invoke(
            monkeypatch,
            [
                "evaluate",
                path,
                "--slice",
                "site",
                "--baseline-column",
                "baseline",
                "--output-dir",
                output,
                "--resamples",
                "100",
            ],
        )
        == 0
    )
    summary = capsys.readouterr().out
    assert (
        "Worst slice" in summary
        and "site=lab-a" in summary
        and "Baseline improvement" in summary
    )
    assert (
        invoke(
            monkeypatch,
            [
                "evaluate",
                path,
                "--slice",
                "site",
                "--output-dir",
                output,
                "--min-slice-size",
                "30",
                "--no-uncertainty",
            ],
        )
        == 0
    )
    assert "insufficient size" in capsys.readouterr().out


def test_protocol_identity_quality_exit_and_disclosure_policy_stay_enforced(
    tmp_path, monkeypatch, capsys
):
    path = table(tmp_path)
    output = tmp_path / "results"
    assert (
        invoke(
            monkeypatch,
            [
                "evaluate",
                path,
                "--protocol",
                "plb://generic/regression@1.0.0",
                "--output-dir",
                output,
            ],
        )
        == 0
    )
    assert "MAE" in capsys.readouterr().out
    receipt = json.loads((output / "evaluation_receipt.json").read_text())
    assert (
        receipt["shareable"]["evaluation"]["protocol"]["id"]
        == "plb://generic/regression"
    )
    assert (
        invoke(
            monkeypatch,
            [
                "evaluate",
                path,
                "--protocol",
                "plb://generic/regression@1.0.0",
                "--resamples",
                "100",
                "--output-dir",
                output,
            ],
        )
        == 2
    )
    quality = tmp_path / "quality.yaml"
    quality.write_text(
        "schema_version: quality-policy/v1\nmetric:\n  rmse:\n    max: 0.01\n"
    )
    release = tmp_path / "release.yaml"
    release.write_text(
        yaml.safe_dump(
            {
                "schema_version": "release-policy/v1",
                "id": "reviewed-synthetic",
                "enabled": True,
                "min_samples": 20,
                "min_cell_size": 5,
                "require_privacy_audit": False,
            }
        )
    )
    args = [
        "evaluate",
        path,
        "--quality-policy",
        quality,
        "--release-policy",
        release,
        "--output-dir",
        output,
        "--resamples",
        "100",
    ]
    assert invoke(monkeypatch, args) == 1
    public = output / "evaluation_receipt.shareable.json"
    assert public.exists() and verify_receipt(public)["valid"]
    path.write_text(path.read_text().replace("private-sample-1,", "private-sample-0,"))
    assert invoke(monkeypatch, args) == 2 and not public.exists()
    assert "must be unique" in capsys.readouterr().out


def test_probabilities_missing_labels_and_output_collisions_are_actionable(
    tmp_path, monkeypatch, capsys
):
    path = tmp_path / "binary.csv"
    output = tmp_path / "results"
    path.write_text("sample_id,target,prediction\na,0,0.1\nb,1,1.5\n")
    args = ["evaluate", path, "--task-type", "classification", "--output-dir", output]
    assert invoke(monkeypatch, args) == 2
    assert "probabilities must be between" in capsys.readouterr().out
    path.write_text("sample_id,target,prediction\na,,0.1\nb,1,0.8\n")
    assert invoke(monkeypatch, args) == 2
    assert "missing labels" in capsys.readouterr().out
    original = path.read_bytes()
    assert invoke(monkeypatch, ["init", path, "--out", path]) == 2
    assert path.read_bytes() == original


def test_compare_conventional_csvs_enters_paired_mode(tmp_path, monkeypatch, capsys):
    a = table(tmp_path)
    b = tmp_path / "candidate.csv"
    b.write_text(a.read_text())
    json_path = tmp_path / "paired.json"
    assert (
        invoke(
            monkeypatch,
            [
                "compare",
                a,
                b,
                "--resamples",
                "100",
                "--permutations",
                "0",
                "--json-report",
                json_path,
                "--report",
                tmp_path / "paired.md",
            ],
        )
        == 0
    )
    assert (
        json.loads(json_path.read_text())["schema_version"]
        == "paired-comparison-artifact/v1"
    )
    assert "paired prediction comparison" in capsys.readouterr().out


def test_multiclass_probability_order_and_manual_config_protection(
    tmp_path, monkeypatch
):
    path = tmp_path / "multiclass.csv"
    path.write_text(
        "sample_id,target,p_a,p_b,p_c\na,a,0.8,0.1,0.1\nb,b,0.1,0.8,0.1\nc,c,0.1,0.1,0.8\n"
    )
    output = tmp_path / "results"
    args = [
        "evaluate",
        path,
        "--prediction-columns",
        "p_a",
        "p_b",
        "p_c",
        "--class-labels",
        "a",
        "b",
        "c",
        "--output-dir",
        output,
    ]
    assert invoke(monkeypatch, args) == 0
    config = output / "evaluation.yaml"
    parsed = yaml.safe_load(config.read_text())
    assert parsed["input"]["class_labels"] == ["a", "b", "c"]
    assert parsed["input"]["task_type"] == "multiclass"
    original = "# Manually authored config\n" + yaml.safe_dump(parsed)
    config.write_text(original)
    assert invoke(monkeypatch, args) == 2 and config.read_text() == original


def test_generated_config_pins_local_protocol_rules(tmp_path, monkeypatch):
    from privatelabbench.config import load_config
    from privatelabbench.protocols import resolve_protocol

    path = table(tmp_path)
    protocol_path = tmp_path / "protocol.yaml"
    rules = resolve_protocol("plb://generic/regression@1.0.0").as_dict()
    protocol_path.write_text(yaml.safe_dump(rules))
    config = tmp_path / "evaluation.yaml"
    assert (
        invoke(
            monkeypatch, ["init", path, "--out", config, "--protocol", protocol_path]
        )
        == 0
    )
    assert (
        load_config(str(config)).protocol.sha256
        == yaml.safe_load(config.read_text())["protocol_sha256"]
    )
    rules["uncertainty"]["seed"] += 1
    protocol_path.write_text(yaml.safe_dump(rules))
    with pytest.raises(ValueError, match="digest changed"):
        load_config(str(config))
