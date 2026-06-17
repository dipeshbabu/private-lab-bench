import json

from privatelabbench.evidence import run_evidence, verify_evidence_manifest
from privatelabbench.reports.manifest import verify_run_manifest
from privatelabbench.sync import sanitize_evidence_summary
from privatelabbench.validation import validate_config


def _write_evidence_config(tmp_path, *, rows: str, minimum_lift: float = 0.10) -> tuple[object, object, object]:
    csv_path = tmp_path / "predictions.csv"
    config_path = tmp_path / "prediction_eval.yaml"
    evidence_md = tmp_path / "evidence.md"
    evidence_json = tmp_path / "evidence.json"
    eval_md = tmp_path / "prediction.md"
    eval_json = tmp_path / "prediction.json"
    manifest = tmp_path / "manifest.json"
    audit = tmp_path / "audit.jsonl"
    csv_path.write_text(rows, encoding="utf-8")
    config_path.write_text(
        f"""
project: evidence-demo
workflow: predictions
claim:
  text: Vendor model improves RMSE versus internal baseline
  decision_metric: rmse
  direction: lower_is_better
  minimum_lift: {minimum_lift}
input:
  path: {csv_path}
  target_column: label
  prediction_column: vendor_pred
  baseline_prediction_column: baseline_pred
  task_type: regression
privacy:
  mode: none
report:
  markdown: {eval_md}
  json: {eval_json}
  manifest: {manifest}
  evidence_markdown: {evidence_md}
  evidence_json: {evidence_json}
audit:
  path: {audit}
""".strip(),
        encoding="utf-8",
    )
    return config_path, evidence_md, evidence_json


def test_evidence_report_recommends_go_when_lift_passes(tmp_path):
    config_path, evidence_md, evidence_json = _write_evidence_config(
        tmp_path,
        rows="\n".join(
            [
                "label,vendor_pred,baseline_pred",
                "0.10,0.11,0.30",
                "0.20,0.21,0.40",
                "0.30,0.31,0.50",
                "0.40,0.39,0.60",
            ]
        )
        + "\n",
    )

    summary = run_evidence(str(config_path))

    assert summary["recommendation"] == "go"
    assert summary["manifest_valid"] is True
    assert evidence_md.exists()
    assert evidence_json.exists()
    payload = json.loads(evidence_json.read_text(encoding="utf-8"))
    assert payload["report_type"] == "model_claim_evidence"
    assert payload["result"]["decision"]["recommendation"] == "go"
    assert payload["result"]["comparison"]["status"] == "pass"
    assert verify_run_manifest(payload["result"]["artifacts"]["run_manifest"])["valid"] is True
    assert verify_evidence_manifest(summary["evidence_manifest"])["valid"] is True
    assert summary["evidence_manifest_valid"] is True
    assert payload["integrity"]["payload_sha256"]
    assert "Model Claim Evidence Report" in evidence_md.read_text(encoding="utf-8")

    sanitized = sanitize_evidence_summary(summary, organization_id="org_1")
    dumped = sanitized.model_dump_json()
    assert sanitized.organization_id == "org_1"
    assert sanitized.recommendation == "go"
    assert sanitized.decision_metric == "rmse"
    assert sanitized.relative_lift is not None
    assert any(artifact.kind == "evidence_manifest" for artifact in sanitized.artifacts)
    assert str(config_path.parent) not in dumped


def test_evidence_report_recommends_no_go_when_lift_fails(tmp_path):
    config_path, _evidence_md, evidence_json = _write_evidence_config(
        tmp_path,
        rows="\n".join(
            [
                "label,vendor_pred,baseline_pred",
                "0.10,0.30,0.11",
                "0.20,0.40,0.21",
                "0.30,0.50,0.31",
                "0.40,0.60,0.39",
            ]
        )
        + "\n",
    )

    summary = run_evidence(str(config_path))

    assert summary["recommendation"] == "no-go"
    payload = json.loads(evidence_json.read_text(encoding="utf-8"))
    assert payload["result"]["decision"]["reasons"] == ["minimum_model_lift_not_met"]
    assert payload["result"]["comparison"]["status"] == "fail"


def test_validation_requires_baseline_prediction_column(tmp_path):
    csv_path = tmp_path / "predictions.csv"
    config_path = tmp_path / "prediction_eval.yaml"
    csv_path.write_text("label,vendor_pred\n0.1,0.1\n0.2,0.2\n", encoding="utf-8")
    config_path.write_text(
        f"""
project: missing-baseline
workflow: predictions
input:
  path: {csv_path}
  target_column: label
  prediction_column: vendor_pred
  baseline_prediction_column: baseline_pred
  task_type: regression
privacy:
  mode: none
""".strip(),
        encoding="utf-8",
    )

    result = validate_config(str(config_path))

    assert not result.valid
    assert any("baseline_pred" in error for error in result.errors)
