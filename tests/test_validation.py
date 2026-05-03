from __future__ import annotations

from argparse import Namespace

from privatelabbench.cli import validate_config_command
from privatelabbench.validation import validate_config


def test_validate_prediction_config_passes(tmp_path):
    config_path = tmp_path / "prediction.yaml"
    md_path = tmp_path / "prediction.md"
    json_path = tmp_path / "prediction.json"
    audit_path = tmp_path / "audit.jsonl"
    config_path.write_text(
        f"""
project: validation-demo
workflow: predictions
input:
  path: examples/predictions_demo.csv
  target_column: label
  prediction_column: pred
  task_type: regression
privacy:
  mode: dp
  epsilon: 8
  sensitivity: 1
  seed: 13
report:
  markdown: {md_path}
  json: {json_path}
audit:
  path: {audit_path}
""".strip(),
        encoding="utf-8",
    )

    result = validate_config(str(config_path))

    assert result.valid
    assert result.project == "validation-demo"
    assert result.workflow == "predictions"
    assert result.errors == []


def test_validate_prediction_config_reports_missing_csv(tmp_path):
    config_path = tmp_path / "prediction.yaml"
    config_path.write_text(
        """
project: missing-file-demo
workflow: predictions
input:
  path: missing.csv
  target_column: label
  prediction_column: pred
privacy:
  mode: none
""".strip(),
        encoding="utf-8",
    )

    result = validate_config(str(config_path))

    assert not result.valid
    assert any("Input file does not exist" in error for error in result.errors)


def test_validate_prediction_config_reports_missing_column(tmp_path):
    csv_path = tmp_path / "predictions.csv"
    csv_path.write_text("label,wrong\n0.1,0.2\n", encoding="utf-8")
    config_path = tmp_path / "prediction.yaml"
    config_path.write_text(
        f"""
project: missing-column-demo
workflow: predictions
input:
  path: {csv_path}
  target_column: label
  prediction_column: pred
privacy:
  mode: none
""".strip(),
        encoding="utf-8",
    )

    result = validate_config(str(config_path))

    assert not result.valid
    assert any("missing required column(s): pred" in error for error in result.errors)


def test_validate_config_command_returns_nonzero_for_invalid_config(tmp_path, capsys):
    config_path = tmp_path / "prediction.yaml"
    config_path.write_text(
        """
project: cli-invalid-demo
workflow: predictions
input:
  path: missing.csv
  target_column: label
  prediction_column: pred
privacy:
  mode: none
""".strip(),
        encoding="utf-8",
    )

    exit_code = validate_config_command(Namespace(config_path=str(config_path)))
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "Valid: False" in output
    assert "Input file does not exist" in output
