import json

from privatelabbench.runner import run_config
from privatelabbench.validation import validate_config


def test_tabular_config_validates_with_required_ids_and_slices():
    result = validate_config("configs/tabular_eval.yaml")
    assert result.valid
    assert not [warning for warning in result.warnings if "sample IDs" in warning]


def test_missing_optional_sample_id_warns(tmp_path):
    csv_path = tmp_path / "legacy.csv"
    csv_path.write_text("target,prediction\n0.1,0.1\n0.2,0.2\n", encoding="utf-8")
    config_path = tmp_path / "legacy.yaml"
    config_path.write_text(
        f"""
project: legacy
task: tabular
input:
  path: {csv_path}
  target_column: target
  prediction_column: prediction
  task_type: regression
  require_sample_id: false
privacy:
  mode: none
""".strip(),
        encoding="utf-8",
    )
    result = validate_config(str(config_path))
    assert result.valid
    assert any("strongly recommended" in warning for warning in result.warnings)


def test_missing_required_sample_id_fails(tmp_path):
    csv_path = tmp_path / "legacy.csv"
    csv_path.write_text("target,prediction\n0.1,0.1\n0.2,0.2\n", encoding="utf-8")
    config_path = tmp_path / "legacy.yaml"
    config_path.write_text(
        f"""
project: legacy
task: tabular
input:
  path: {csv_path}
  target_column: target
  prediction_column: prediction
  task_type: regression
  require_sample_id: true
privacy:
  mode: none
""".strip(),
        encoding="utf-8",
    )
    result = validate_config(str(config_path))
    assert not result.valid
    assert any("Stable sample IDs are strongly recommended" in error for error in result.errors)


def test_missing_slice_column_fails_validation(tmp_path):
    csv_path = tmp_path / "table.csv"
    csv_path.write_text("sample_id,target,prediction\na,0.1,0.1\nb,0.2,0.2\n", encoding="utf-8")
    config_path = tmp_path / "table.yaml"
    config_path.write_text(
        f"""
project: slices
task: tabular
input:
  path: {csv_path}
  sample_id_column: sample_id
  require_sample_id: true
  target_column: target
  prediction_column: prediction
  task_type: regression
  slice_columns:
    - site
privacy:
  mode: none
""".strip(),
        encoding="utf-8",
    )
    result = validate_config(str(config_path))
    assert not result.valid
    assert any("missing required column(s): site" in error for error in result.errors)


def test_multiclass_config_validates_runs_and_keeps_rows_private(tmp_path):
    validation = validate_config("configs/multiclass_eval.yaml")
    assert validation.valid

    config_path = tmp_path / "multiclass.yaml"
    report_path = tmp_path / "multiclass.md"
    json_path = tmp_path / "multiclass.json"
    manifest_path = tmp_path / "multiclass_manifest.json"
    audit_path = tmp_path / "multiclass_audit.jsonl"
    config_path.write_text(
        f"""
project: multiclass-test
task: tabular
input:
  path: examples/multiclass_predictions_demo.csv
  sample_id_column: sample_id
  require_sample_id: true
  target_column: target
  prediction_columns:
    - p_alpha
    - p_beta
    - p_gamma
  class_labels:
    - alpha
    - beta
    - gamma
  task_type: multiclass
  slice_columns:
    - site
  min_slice_size: 2
privacy:
  mode: none
report:
  markdown: {report_path}
  json: {json_path}
  manifest: {manifest_path}
audit:
  path: {audit_path}
""".strip(),
        encoding="utf-8",
    )
    summary = run_config(str(config_path))
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)
    assert summary["task_type"] == "multiclass"
    assert summary["clean_metrics"]["accuracy"] == 1.0
    assert payload["result"]["sharing_boundary"]["row_level_values_included"] is False
    assert payload["result"]["slice_metrics"]["site"]["north"]["n"] == 3
    assert "mc001" not in serialized
