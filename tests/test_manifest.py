import json

from privatelabbench.privacy.dp import PrivacyConfig
from privatelabbench.reports.json import write_json_report
from privatelabbench.reports.manifest import verify_run_manifest, write_run_manifest


def test_run_manifest_verifies_bound_artifacts(tmp_path):
    config_path = tmp_path / "config.yaml"
    audit_path = tmp_path / "audit.jsonl"
    markdown_path = tmp_path / "report.md"
    report_path = tmp_path / "report.json"
    manifest_path = tmp_path / "manifest.json"
    config_path.write_text("project: demo\nworkflow: predictions\n", encoding="utf-8")
    audit_path.write_text('{"event_type":"evaluation_completed"}\n', encoding="utf-8")
    markdown_path.write_text("# Demo\n", encoding="utf-8")
    write_json_report(
        str(report_path),
        report_type="prediction_evaluation",
        result={"project": "demo", "reported_metrics": {"rmse": 0.1}},
        privacy_config=PrivacyConfig(mode="none"),
        signing_secret="secret",
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = {
        "project": "demo",
        "workflow": "predictions",
        "run_id": report["run_id"],
        "benchmark_id": "demo-benchmark",
        "benchmark_version": "v1",
        "benchmark_suite": "unit",
        "domain": "molecules",
        "runner_id": "runner-1",
    }

    write_run_manifest(
        manifest_path,
        summary=summary,
        config_path=config_path,
        json_report_path=report_path,
        markdown_report_path=markdown_path,
        audit_log_path=audit_path,
        signing_secret="secret",
    )

    result = verify_run_manifest(manifest_path, signing_secret="secret")

    assert result["valid"] is True
    assert result["run_id"] == report["run_id"]
    assert result["artifacts_valid"] is True
    assert result["report_valid"] is True
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["attestation"]["schema_version"] == "runner-attestation/v0.1"
    assert manifest["attestation"]["package"]["name"] == "private-lab-bench"
    assert manifest["attestation"]["attestation_id"]


def test_run_manifest_detects_tampered_artifact(tmp_path):
    config_path = tmp_path / "config.yaml"
    audit_path = tmp_path / "audit.jsonl"
    report_path = tmp_path / "report.json"
    manifest_path = tmp_path / "manifest.json"
    config_path.write_text("project: demo\nworkflow: predictions\n", encoding="utf-8")
    audit_path.write_text('{"event_type":"evaluation_completed"}\n', encoding="utf-8")
    write_json_report(
        str(report_path),
        report_type="prediction_evaluation",
        result={"project": "demo"},
        privacy_config=PrivacyConfig(mode="none"),
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    write_run_manifest(
        manifest_path,
        summary={"project": "demo", "workflow": "predictions", "run_id": report["run_id"]},
        config_path=config_path,
        json_report_path=report_path,
        audit_log_path=audit_path,
    )
    audit_path.write_text('{"event_type":"tampered"}\n', encoding="utf-8")

    result = verify_run_manifest(manifest_path)

    assert result["valid"] is False
    assert result["reason"] == "artifact_hash_check_failed"
