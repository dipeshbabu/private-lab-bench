import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from privatelabbench.privacy.export import check_release, publish_shareable_artifact
from privatelabbench.reports.integrity import verify_report
from privatelabbench.runner import run_config


def policy(**changes):
    return {"schema_version": "release-policy/v1", "id": "synthetic-test", "enabled": True, "min_samples": 2, "min_cell_size": 2, "require_privacy_audit": False, **changes}


def candidate():
    return {
        "schema_version": "evaluation-receipt/v1", "receipt_id": "SECRET", "created_at": "SECRET", "scope": "local",
        "local": {"path": "/SECRET/private.csv", "exact_metrics": {"mae": 99}},
        "shareable": {
            "run": {"project": "SECRET", "task": "SECRET"}, "benchmark": {"id": "SECRET"},
            "evaluation": {"task_type": "regression", "sample_counts": {"n_samples": 8}, "input_schema": {"schema_version": "prediction-table/v1", "sample_id_column": "SECRET"}, "metrics": {"mae": 0.2, "rmse": 0.3}, "metric_source": "reported_metrics", "uncertainty": {}, "slices": {}},
            "privacy": {"mechanism": {"mode": "none"}, "audits": {}, "release": {"status": "pass", "publishable": True}},
            "provenance": {"secret": "SECRET"}, "artifacts": [{"name": "SECRET"}], "plugin": {"raw": ["SECRET"]},
        },
    }


@pytest.mark.parametrize("invalid", [None, {}, {"schema_version": "release-policy/v2"}, policy(enabled="true"), policy(min_samples=0), policy(unknown=True), policy(slices={"site": ["a"], "batch": ["b"]})])
def test_missing_or_invalid_policy_cannot_publish(tmp_path, invalid):
    output = tmp_path / "run.shareable.json"
    output.write_text("stale sensitive export")
    decision = publish_shareable_artifact(candidate(), invalid, output)
    assert decision.decision == "needs_review"
    assert not output.exists()
    audit = json.loads(output.with_suffix(".release-audit.json").read_text())
    assert audit["scope"] == "local"


def test_allowlist_removes_private_and_plugin_fields_and_matches_schema(tmp_path):
    value = candidate()
    value["shareable"]["evaluation"]["uncertainty"] = {"status": "evaluated", "reason": "SECRET", "metrics": {"mae": {"estimate": 0.2, "lower": 0.1, "upper": 0.3, "status": "evaluated", "rows": ["SECRET"]}}}
    output = tmp_path / "receipt.shareable.json"
    assert publish_shareable_artifact(value, policy(), output).decision == "allow"
    payload = json.loads(output.read_text())
    assert "SECRET" not in json.dumps(payload)
    assert payload["shareable"]["evaluation"]["metrics"]["mae"] == 0.2
    assert verify_report(str(output))["valid"]
    schema = json.loads(Path("privatelabbench/data/schemas/evaluation-receipt-v1.schema.json").read_text())
    jsonschema.validate(payload, schema)


@pytest.mark.parametrize("gate", [{"status": "fail", "publishable": False}, {"status": "pass"}, {"status": "unknown", "publishable": True}, "malformed"])
def test_every_gate_must_explicitly_pass(gate):
    decision, result = check_release(candidate(), policy(), evidence={"gates": [{"status": "pass", "publishable": True}, gate]})
    assert decision.decision != "allow"
    assert result is None


@pytest.mark.parametrize("audit,expected", [(None, "not_run"), ({"risk_level": "unknown"}, "inconclusive")])
def test_required_audit_never_treats_missing_evidence_as_privacy(audit, expected):
    decision, result = check_release(candidate(), policy(require_privacy_audit=True), evidence={"gates": [], "audit": audit})
    assert decision.audit_status == expected
    assert decision.decision == "needs_review"
    assert result is None


def test_small_cells_suppress_entire_partition_and_overlapping_scans_stay_local():
    value = candidate()
    value["shareable"]["evaluation"]["slices"] = {"site": {"a": {"n": 7, "metrics": {"mae": 0.2}}, "b": {"n": 1, "metrics": {"mae": 0.1}}}, "private_batch": {"SECRET": {"n": 8}}}
    decision, output = check_release(value, policy(slices={"site": ["a", "b"]}))
    assert decision.decision == "allow"
    assert output["shareable"]["evaluation"]["slices"] == {}


def test_clean_intervals_and_slices_are_withheld_for_perturbed_metrics():
    value = candidate()
    value["shareable"]["privacy"]["mechanism"]["mode"] = "metric_perturbation"
    value["shareable"]["evaluation"]["uncertainty"] = {"status": "evaluated", "metric_basis": "clean_metrics", "metrics": {"mae": {"estimate": 999, "lower": 900, "upper": 1000}}}
    decision, output = check_release(value, policy())
    assert decision.decision == "allow"
    released = output["shareable"]["evaluation"]
    assert released["uncertainty"] == {"status": "withheld_metric_basis_mismatch", "metric_basis": "clean_metrics", "released_metric_basis": "reported_metrics"}
    assert released["metrics"] == {"mae": 0.2, "rmse": 0.3}
    assert released["slices"] == {}


def test_repeated_changed_releases_require_audited_review(tmp_path):
    output = tmp_path / "receipt.shareable.json"
    value = candidate()
    assert publish_shareable_artifact(value, policy(), output).decision == "allow"
    assert publish_shareable_artifact(value, policy(), output).decision == "allow"
    value["shareable"]["evaluation"]["metrics"]["mae"] = 0.25
    decision = publish_shareable_artifact(value, policy(), output)
    assert decision.reason_codes == ("changed_repeated_release_requires_review",)
    assert not output.exists()
    assert publish_shareable_artifact(value, policy(reviewed_repeat=True), output).decision == "needs_review"
    assert publish_shareable_artifact(value, policy(reviewed_repeat=True, review_reference="local-review-2"), output).decision == "allow"
    audit = json.loads(output.with_suffix(".release-audit.json").read_text())
    assert audit["review_reference"] == "local-review-2"


def test_interrupted_export_leaves_no_partial_or_stale_file(tmp_path, monkeypatch):
    import privatelabbench.privacy.export as exports
    output = tmp_path / "receipt.shareable.json"
    output.write_text("stale")
    original_replace = exports.os.replace

    def fail_export(source, destination):
        if destination == output:
            raise OSError("simulated full disk")
        original_replace(source, destination)

    monkeypatch.setattr(exports.os, "replace", fail_export)
    assert publish_shareable_artifact(candidate(), policy(), output).decision == "needs_review"
    assert not output.exists()
    assert not list(tmp_path.glob(".plb-*.tmp"))


def test_ledger_lock_cannot_be_silently_overridden(tmp_path):
    lock = tmp_path / ".plb-release.lock"
    lock.write_text("other publisher")
    output = tmp_path / "receipt.shareable.json"
    assert publish_shareable_artifact(candidate(), policy(), output).decision == "needs_review"
    assert lock.read_text() == "other publisher"
    assert not output.exists()


def test_config_gate_failure_preserves_local_results_and_removes_previous_export(tmp_path):
    config = yaml.safe_load(Path("configs/tabular_eval.yaml").read_text())
    config["report"] = {"json": str(tmp_path / "run.json"), "markdown": str(tmp_path / "run.md"), "manifest": str(tmp_path / "run_manifest.json")}
    config["audit"] = {"path": str(tmp_path / "audit.jsonl")}
    config_path = tmp_path / "run.yaml"
    config_path.write_text(yaml.safe_dump(config))
    run_config(str(config_path))
    shareable = tmp_path / "run_receipt.shareable.json"
    assert shareable.exists()
    config["privacy"]["risk_policy"] = {"require_attack": True}
    config_path.write_text(yaml.safe_dump(config))
    summary = run_config(str(config_path))
    assert summary["privacy_gate_publishable"] is False
    assert not shareable.exists()
    assert (tmp_path / "run_receipt.json").exists()
    assert (tmp_path / "run.json").exists()
    assert "Export blocked" in (tmp_path / "run_receipt.md").read_text()


def test_unknown_metric_values_and_statistical_free_text_fail_closed():
    value = candidate()
    value["shareable"]["evaluation"]["metrics"]["mae"] = "SECRET"
    assert check_release(value, policy())[0].decision == "needs_review"
    value = candidate()
    value["shareable"]["evaluation"]["uncertainty"] = {"status": "SECRET"}
    assert check_release(value, policy())[0].decision == "needs_review"


def test_direct_cli_reports_stay_local(tmp_path, monkeypatch):
    from privatelabbench.cli import main
    csv = tmp_path / "predictions.csv"
    csv.write_text("sample_id,target,prediction\ns1,0.1,0.2\ns2,0.3,0.4\ns3,0.5,0.4\n")
    report = tmp_path / "direct.json"
    monkeypatch.setattr("sys.argv", ["plb", "eval-predictions", str(csv), "--target", "target", "--prediction-column", "prediction", "--task-type", "regression", "--json-report", str(report), "--report", str(tmp_path / "direct.md")])
    assert main() == 0
    assert json.loads(report.read_text())["scope"] == "local"
    assert not list(tmp_path.glob("*.shareable.json"))


def test_paired_exports_use_same_boundary_and_schema(tmp_path):
    from privatelabbench.eval.paired_comparison import PairedComparisonConfig, compare_prediction_tables
    from privatelabbench.reports.paired_comparison import write_paired_comparison_artifacts
    csv = tmp_path / "predictions.csv"
    csv.write_text("sample_id,target,prediction\ns1,0.1,0.2\ns2,0.3,0.4\ns3,0.5,0.4\n")
    result = compare_prediction_tables(str(csv), str(csv), target="target", task_type="regression", config=PairedComparisonConfig(resamples=100, permutations=0, min_samples=2))
    local = tmp_path / "paired.json"
    paths = write_paired_comparison_artifacts(json_path=local, markdown_path=tmp_path / "paired.md", result=result, path_a=csv, path_b=csv, release_policy=policy())
    payload = json.loads(paths["shareable_json_report"].read_text())
    schema = json.loads(Path("privatelabbench/data/schemas/paired-comparison-artifact-v1.schema.json").read_text())
    jsonschema.validate(payload, schema)
    paths = write_paired_comparison_artifacts(json_path=local, markdown_path=tmp_path / "paired.md", result=result, path_a=csv, path_b=csv)
    assert "shareable_json_report" not in paths
    assert not (tmp_path / "paired.shareable.json").exists()
    assert local.exists()


def test_synthetic_policies_match_the_versioned_policy_schema():
    schema = json.loads(Path("privatelabbench/data/schemas/release-policy-v1.schema.json").read_text())
    for path in [*Path("configs").glob("*.yaml"), *Path("privatelabbench/data/benchmark_packs").glob("*/config.yaml")]:
        jsonschema.validate(yaml.safe_load(path.read_text())["release"], schema)
