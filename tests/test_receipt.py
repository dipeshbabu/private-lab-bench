from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from privatelabbench.cli import verify_any_command
from privatelabbench.reports.receipt import (
    RECEIPT_SCHEMA_VERSION,
    normalize_receipt,
    verify_receipt,
)
from privatelabbench.runner import run_config


def _write_config(tmp_path: Path, *, signing_secret: str | None = None, privacy_mode: str = "none") -> Path:
    config_path = tmp_path / "receipt.yaml"
    md_path = tmp_path / "eval.md"
    json_path = tmp_path / "eval.json"
    manifest_path = tmp_path / "eval_manifest.json"
    audit_path = tmp_path / "audit.jsonl"
    signing_line = f"  signing_secret: {signing_secret}\n" if signing_secret else ""
    config_path.write_text(
        f"""
project: receipt-test
task: tabular
benchmark:
  id: receipt-test-benchmark
  version: "1.0"
  suite: generic-tabular
  domain: tabular
  protocol: prediction-table/v1
input:
  path: examples/tabular_predictions_demo.csv
  sample_id_column: sample_id
  require_sample_id: true
  target_column: target
  prediction_column: prediction
  task_type: regression
  slice_columns:
    - site
  min_slice_size: 2
privacy:
  mode: {privacy_mode}
  epsilon: 0.5
  sensitivity: 1.0
  seed: 7
report:
  markdown: {md_path}
  json: {json_path}
  manifest: {manifest_path}
{signing_line}audit:
  path: {audit_path}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return config_path


def _receipt_paths(manifest_path: Path) -> tuple[Path, Path, Path]:
    return (
        manifest_path.with_name("eval_receipt.json"),
        manifest_path.with_name("eval_receipt.shareable.json"),
        manifest_path.with_name("eval_receipt.md"),
    )


def test_config_run_writes_local_shareable_and_markdown_receipts(tmp_path):
    config_path = _write_config(tmp_path)
    summary = run_config(str(config_path))
    manifest_path = Path(summary["manifest"])
    local_path, shareable_path, markdown_path = _receipt_paths(manifest_path)

    assert local_path.exists()
    assert shareable_path.exists()
    assert markdown_path.exists()

    local = json.loads(local_path.read_text(encoding="utf-8"))
    shareable = json.loads(shareable_path.read_text(encoding="utf-8"))
    report = json.loads(Path(summary["json_report"]).read_text(encoding="utf-8"))

    assert local["schema_version"] == RECEIPT_SCHEMA_VERSION
    assert local["scope"] == "local"
    assert local["local"]["sharing"] == "local_only"
    assert local["local"]["config_snapshot"]["project"] == "receipt-test"
    assert shareable["scope"] == "shareable"
    assert "local" not in shareable
    assert shareable["shareable"]["evaluation"]["metrics"] == report["result"]["reported_metrics"]
    assert shareable["shareable"]["evaluation"]["input_schema"]["schema_version"] == "prediction-table/v1"
    assert shareable["shareable"]["evaluation"]["slices"]["site"]

    serialized_shareable = json.dumps(shareable)
    assert str(config_path) not in serialized_shareable
    assert "examples/tabular_predictions_demo.csv" not in serialized_shareable
    assert "config_snapshot" not in serialized_shareable
    assert "exact_metrics" not in serialized_shareable

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "PrivateLabBench Evaluation Receipt" in markdown
    assert "Sharing boundary" in markdown
    assert str(config_path) not in markdown


def test_receipt_separates_released_and_exact_metrics(tmp_path):
    config_path = _write_config(tmp_path, privacy_mode="dp")
    summary = run_config(str(config_path))
    local_path, shareable_path, _ = _receipt_paths(Path(summary["manifest"]))
    local = json.loads(local_path.read_text(encoding="utf-8"))
    shareable = json.loads(shareable_path.read_text(encoding="utf-8"))
    report = json.loads(Path(summary["json_report"]).read_text(encoding="utf-8"))

    assert local["local"]["exact_metrics"] == report["result"]["clean_metrics"]
    assert shareable["shareable"]["evaluation"]["metrics"] == report["result"]["reported_metrics"]
    assert shareable["shareable"]["evaluation"]["metric_source"] == "reported_metrics"


def test_receipts_verify_and_tampering_fails(tmp_path):
    config_path = _write_config(tmp_path)
    summary = run_config(str(config_path))
    local_path, shareable_path, _ = _receipt_paths(Path(summary["manifest"]))

    assert verify_receipt(local_path)["valid"] is True
    assert verify_receipt(shareable_path)["valid"] is True

    payload = json.loads(shareable_path.read_text(encoding="utf-8"))
    payload["shareable"]["evaluation"]["metrics"]["mae"] = 999.0
    shareable_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    check = verify_receipt(shareable_path)
    assert check["valid"] is False
    assert check["reason"] == "hash_check_failed"


def test_signed_receipts_verify_with_secret(tmp_path):
    secret = "receipt-test-secret"
    config_path = _write_config(tmp_path, signing_secret=secret)
    summary = run_config(str(config_path))
    local_path, shareable_path, _ = _receipt_paths(Path(summary["manifest"]))

    for path in (local_path, shareable_path):
        result = verify_receipt(path, signing_secret=secret)
        assert result["valid"] is True
        assert result["signature_valid"] is True

    wrong = verify_receipt(shareable_path, signing_secret="wrong-secret")
    assert wrong["valid"] is False
    assert wrong["reason"] == "signature_check_failed"


def test_plb_verify_dispatches_receipts_and_legacy_artifacts(tmp_path, capsys):
    config_path = _write_config(tmp_path)
    summary = run_config(str(config_path))
    _, shareable_path, _ = _receipt_paths(Path(summary["manifest"]))

    receipt_code = verify_any_command(Namespace(artifact=str(shareable_path), signing_secret=None))
    receipt_output = capsys.readouterr().out
    assert receipt_code == 0
    assert "Schema: evaluation-receipt/v1" in receipt_output
    assert "Scope: shareable" in receipt_output

    manifest_code = verify_any_command(Namespace(artifact=summary["manifest"], signing_secret=None))
    assert manifest_code == 0

    report_code = verify_any_command(Namespace(artifact=summary["json_report"], signing_secret=None))
    assert report_code == 0


def test_legacy_run_manifest_has_receipt_compatibility_view(tmp_path):
    config_path = _write_config(tmp_path)
    summary = run_config(str(config_path))
    manifest = json.loads(Path(summary["manifest"]).read_text(encoding="utf-8"))

    compatible = normalize_receipt(manifest)
    assert compatible["schema_version"] == RECEIPT_SCHEMA_VERSION
    assert compatible["scope"] == "compatibility"
    assert compatible["local"]["legacy_schema"] == "run-manifest/v0.1"
    assert compatible["shareable"]["run"]["run_id"] == manifest["run"]["run_id"]
    assert compatible["shareable"]["evaluation"]["metric_source"] == "not_present_in_legacy_manifest"


def test_checked_in_example_receipt_verifies():
    result = verify_receipt("examples/reports/evaluation_receipt_example.json")
    assert result["valid"] is True
    payload = json.loads(Path("examples/reports/evaluation_receipt_example.json").read_text(encoding="utf-8"))
    assert payload["scope"] == "shareable"
    assert "local" not in payload
