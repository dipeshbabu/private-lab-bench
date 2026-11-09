import json
import sys
from pathlib import Path

import pytest
import yaml

from privatelabbench.cli import main
from privatelabbench.reports.receipt import verify_receipt


@pytest.mark.parametrize("approved_export", [False, True])
@pytest.mark.parametrize("task", ["predictions", "federated"])
def test_cli_summary_separates_screening_from_export(
    tmp_path, monkeypatch, capsys, task, approved_export
):
    if task == "predictions":
        predictions = tmp_path / "synthetic.csv"
        predictions.write_text(
            "sample_id,target,prediction\n"
            + "".join(f"s-{i},{i / 10},{i / 10 + 0.05}\n" for i in range(24)),
            encoding="utf-8",
        )
        inputs = {
            "path": str(predictions),
            "target_column": "target",
            "prediction_column": "prediction",
            "task_type": "regression",
        }
        screening_label = "Privacy risk screening: pass"
        gate_name = "privacy_gate"
    else:
        inputs = {
            "client_dir": str(Path("examples/labs").resolve()),
            "target_column": "label",
            "smiles_column": "smiles",
            "task_type": "regression",
        }
        screening_label = "Aggregate screening: pass"
        gate_name = "aggregate_release"
    config = {
        "project": "summary-test",
        "task": task,
        "input": inputs,
        "privacy": {"mode": "none"},
        "report": {
            "markdown": str(tmp_path / "evaluation.md"),
            "json": str(tmp_path / "evaluation.json"),
            "manifest": str(tmp_path / "evaluation_manifest.json"),
        },
        "audit": {"path": str(tmp_path / "audit.jsonl")},
    }
    if approved_export:
        # Both input sources are synthetic; the waiver belongs only to this fixture.
        config["release"] = {
            "schema_version": "release-policy/v1",
            "id": "synthetic-summary-test",
            "enabled": True,
            "min_samples": 2,
            "min_cell_size": 2,
            "require_privacy_audit": False,
        }
    config_path = tmp_path / "evaluation.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["plb", "run", str(config_path)])

    assert main() == 0

    output = capsys.readouterr().out
    report = json.loads((tmp_path / "evaluation.json").read_text(encoding="utf-8"))
    assert report["result"][gate_name]["status"] == "pass"
    assert report["result"][gate_name]["publishable"] is True
    assert screening_label in output
    assert "shareable: true" not in output
    assert (tmp_path / "evaluation_receipt.json").is_file()
    shareable = tmp_path / "evaluation_receipt.shareable.json"
    if approved_export:
        assert shareable.is_file()
        assert verify_receipt(shareable)["valid"] is True
        assert f"Shareable receipt saved to: {shareable}" in output
        assert "Export blocked" not in output
    else:
        assert not shareable.exists()
        assert "Shareable receipt saved to:" not in output
        assert "Export blocked; see:" in output
