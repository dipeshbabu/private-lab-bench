import json
import warnings

from privatelabbench.cli import build_parser, list_privacy_attacks_command
from privatelabbench.runner import run_config


def test_cli_exposes_metric_perturbation_and_attack_discovery(capsys):
    parser = build_parser()
    args = parser.parse_args(
        [
            "eval-predictions",
            "examples/tabular_predictions_demo.csv",
            "--target",
            "target",
            "--prediction-column",
            "prediction",
            "--privacy",
            "metric_perturbation",
        ]
    )
    assert args.privacy == "metric_perturbation"

    assert list_privacy_attacks_command() == 0
    output = capsys.readouterr().out
    assert "loss-threshold-membership-inference" in output
    assert "[baseline]" in output
    assert "empirical_audit" in output


def test_report_and_receipt_mark_metric_perturbation_as_non_formal(tmp_path):
    config_path = tmp_path / "privacy.yaml"
    json_path = tmp_path / "eval.json"
    md_path = tmp_path / "eval.md"
    manifest_path = tmp_path / "eval_manifest.json"
    audit_path = tmp_path / "audit.jsonl"
    config_path.write_text(
        f"""
project: privacy-report
task: tabular
input:
  path: examples/tabular_predictions_demo.csv
  sample_id_column: sample_id
  require_sample_id: true
  target_column: target
  prediction_column: prediction
  task_type: regression
privacy:
  mode: metric_perturbation
  epsilon: 4
  sensitivity: 0.25
  seed: 3
report:
  markdown: {md_path}
  json: {json_path}
  manifest: {manifest_path}
audit:
  path: {audit_path}
""".strip(),
        encoding="utf-8",
    )

    summary = run_config(str(config_path))
    report = json.loads(json_path.read_text(encoding="utf-8"))
    receipt = json.loads((tmp_path / "eval_receipt.shareable.json").read_text(encoding="utf-8"))

    assert report["privacy"]["configured_mode"] == "metric_perturbation"
    assert report["privacy"]["mechanism"] == "metric_perturbation"
    assert report["privacy"]["guarantee_level"] == "heuristic_no_dp_guarantee"
    assert report["privacy"]["formal_dp"] is False
    assert report["privacy"]["user_supplied_scale_sensitivity"] == 0.25
    assert receipt["shareable"]["privacy"]["mechanism"]["formal_dp"] is False
    assert summary["manifest"] == str(manifest_path)


def test_legacy_dp_config_remains_compatible_but_reports_alias(tmp_path):
    config_path = tmp_path / "legacy.yaml"
    json_path = tmp_path / "eval.json"
    md_path = tmp_path / "eval.md"
    manifest_path = tmp_path / "eval_manifest.json"
    audit_path = tmp_path / "audit.jsonl"
    config_path.write_text(
        f"""
project: legacy-privacy
task: tabular
input:
  path: examples/tabular_predictions_demo.csv
  target_column: target
  prediction_column: prediction
  task_type: regression
privacy:
  mode: dp
  epsilon: 8
  sensitivity: 1
  seed: 13
report:
  markdown: {md_path}
  json: {json_path}
  manifest: {manifest_path}
audit:
  path: {audit_path}
""".strip(),
        encoding="utf-8",
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        run_config(str(config_path))
    report = json.loads(json_path.read_text(encoding="utf-8"))

    assert any("deprecated" in str(item.message) for item in caught)
    assert report["privacy"]["configured_mode"] == "dp"
    assert report["privacy"]["mode"] == "metric_perturbation"
    assert report["privacy"]["legacy_dp_alias"] is True
    assert report["privacy"]["formal_dp"] is False
