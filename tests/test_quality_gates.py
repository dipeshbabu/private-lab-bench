from copy import deepcopy
import json
from pathlib import Path

import pytest
import jsonschema
import yaml

from privatelabbench.cli import main
from privatelabbench.quality import evaluate_quality_gate, validate_quality_policy
from privatelabbench.reports.manifest import verify_run_manifest


def policy(**rules):
    return {"schema_version": "quality-policy/v1", **rules}


def report():
    return {"schema_version": "0.2", "scope": "local", "privacy": {"mode": "none"}, "result": {"n_samples": 50, "clean_metrics": {"rmse": 0.3, "auroc": 0.8}, "reported_metrics": {"rmse": 0.3, "auroc": 0.8}, "baseline_metrics": {"rmse": 0.25, "auroc": 0.85}, "uncertainty": {"metric_basis": "clean_metrics", "metrics": {"rmse": {"status": "evaluated", "lower": 0.25, "upper": 0.36}}}, "slice_metrics": {"site": {"internal": {"status": "evaluated", "n": 30, "metrics": {"rmse": 0.2}}, "external": {"status": "evaluated", "n": 20, "metrics": {"rmse": 0.5}}}}}}


def test_exact_thresholds_and_undefined_metrics_have_distinct_states():
    artifact = report()
    assert evaluate_quality_gate(artifact, policy(metric={"rmse": {"max": 0.3}}))["status"] == "pass"
    assert evaluate_quality_gate(artifact, policy(metric={"rmse": {"max": 0.29}}))["status"] == "fail"
    artifact["result"]["clean_metrics"]["rmse"] = float("nan")
    result = evaluate_quality_gate(artifact, policy(metric={"rmse": {"max": 0.3}}))
    assert result["status"] == "investigate" and result["rules"][0]["observed"] is None
    assert evaluate_quality_gate(report(), policy(metric={"r2": {"min": 0.7}}))["status"] == "investigate"


def test_bundled_policy_has_a_versioned_schema():
    example = yaml.safe_load(Path("examples/quality_policy.yaml").read_text())
    schema = json.loads(Path("privatelabbench/data/schemas/quality-policy-v1.schema.json").read_text())
    jsonschema.validate(example, schema)
    validate_quality_policy(example)


def test_uncertainty_gates_require_compatible_available_intervals():
    artifact = report()
    assert evaluate_quality_gate(artifact, policy(metric={"rmse": {"max_ci_upper": 0.35}}))["status"] == "fail"
    artifact["result"]["uncertainty"]["metrics"]["rmse"]["status"] = "insufficient_valid_resamples"
    assert evaluate_quality_gate(artifact, policy(metric={"rmse": {"max_ci_upper": 0.4}}))["status"] == "investigate"
    artifact["privacy"]["mode"] = "metric_perturbation"
    artifact["result"]["uncertainty"]["metrics"]["rmse"]["status"] = "evaluated"
    assert evaluate_quality_gate(artifact, policy(metric_basis="reported", metric={"rmse": {"max_ci_upper": 0.4}}))["status"] == "investigate"


def test_baseline_rules_handle_both_metric_directions_and_zero_reference():
    artifact = report()
    assert evaluate_quality_gate(artifact, policy(baseline={"metric": "rmse", "allow_relative_regression": 0.1}))["status"] == "fail"
    assert evaluate_quality_gate(artifact, policy(baseline={"metric": "auroc", "allow_absolute_regression": 0.01}))["status"] == "fail"
    artifact["result"]["baseline_metrics"]["rmse"] = 0
    result = evaluate_quality_gate(artifact, policy(baseline={"metric": "rmse", "allow_relative_regression": 0.1}))
    assert result["status"] == "investigate"
    assert result["rules"][0]["reason"] == "baseline_missing_undefined_or_zero"


def test_paired_practical_improvement_uses_the_joint_interval():
    artifact = {"schema_version": "paired-comparison-artifact/v1", "scope": "shareable", "shareable": {"n_samples": 80, "model_a": {"metrics": {"rmse": 0.2}}, "model_b": {"metrics": {"rmse": 0.3}}, "improvement_a_over_b": 0.1, "paired_interval": {"status": "evaluated", "lower": 0.02, "upper": 0.18}}}
    assert evaluate_quality_gate(artifact, policy(comparison={"min_improvement": 0.05}))["status"] == "pass"
    assert evaluate_quality_gate(artifact, policy(comparison={"min_improvement": 0.05, "require_confident": True}))["status"] == "fail"
    artifact["shareable"]["paired_interval"]["status"] = "skipped_min_samples"
    assert evaluate_quality_gate(artifact, policy(comparison={"min_improvement": 0.05, "require_confident": True}))["status"] == "investigate"


def test_worst_and_critical_slices_do_not_silently_ignore_missing_groups():
    artifact = report()
    assert evaluate_quality_gate(artifact, policy(slices={"worst_rmse_max": 0.45}))["status"] == "fail"
    critical = {"external": {"column": "site", "value": "external", "metric": "rmse", "max": 0.45}}
    assert evaluate_quality_gate(artifact, policy(slices={"critical": critical}))["status"] == "fail"
    artifact["result"]["slice_metrics"]["site"]["external"] = {"n": 1, "status": "skipped_min_slice_size"}
    assert evaluate_quality_gate(artifact, policy(slices={"worst_rmse_max": 0.45}))["status"] == "investigate"
    assert evaluate_quality_gate(artifact, policy(slices={"critical": critical}))["status"] == "investigate"


def test_worst_slice_uses_metric_direction_independently_of_the_bound():
    artifact = report()
    artifact["result"]["slice_metrics"] = {"site": {"a": {"status": "evaluated", "metrics": {"auroc": 0.95}}, "b": {"status": "evaluated", "metrics": {"auroc": 0.5}}}}
    assert evaluate_quality_gate(artifact, policy(slices={"worst_auroc_min": 0.8}))["status"] == "fail"
    assert evaluate_quality_gate(artifact, policy(slices={"worst_auroc_max": 0.6}))["status"] == "pass"


def test_privacy_requirements_distinguish_audit_execution_from_allowed_risk():
    artifact = report()
    artifact["result"].update(privacy_risk={"risk_level": "high"}, privacy_gate={"status": "fail", "publishable": False})
    assert evaluate_quality_gate(artifact, policy(privacy={"require_audit": True}))["status"] == "pass"
    assert evaluate_quality_gate(artifact, policy(privacy={"require_release": True}))["status"] == "fail"
    assert evaluate_quality_gate(artifact, policy(privacy={"max_level": "low"}))["status"] == "fail"


def test_gate_disclosure_is_opt_in_and_only_releases_status():
    from privatelabbench.privacy.export import check_release
    artifact = json.loads(Path("examples/reports/evaluation_receipt_example.json").read_text())
    artifact["shareable"]["privacy"]["release"] = {"status": "pass", "publishable": True}
    artifact["shareable"]["evaluation"]["quality_gate"] = {"schema_version": "quality-gate/v1", "status": "fail", "policy": {"PRIVATE_SELECTOR": "PRIVATE_VALUE"}, "rules": [{"observed": 999}]}
    disclosure = {"schema_version": "release-policy/v1", "id": "synthetic-quality-review", "enabled": True, "min_samples": 2, "require_privacy_audit": False}
    decision, shared = check_release(artifact, disclosure)
    assert decision.decision == "allow" and "quality_gate" not in shared["shareable"]["evaluation"]
    decision, shared = check_release(artifact, {**disclosure, "include_quality_gate": True})
    assert decision.decision == "allow"
    assert shared["shareable"]["evaluation"]["quality_gate"] == {"schema_version": "quality-gate/v1", "status": "fail"}


def test_shareable_perturbed_metrics_cannot_be_used_as_hidden_clean_evidence():
    shared = {"schema_version": "evaluation-receipt/v1", "scope": "shareable", "shareable": {"evaluation": {"metrics": {"rmse": 0.2}, "sample_counts": {"n_samples": 50}}, "privacy": {"mechanism": {"mode": "metric_perturbation"}, "audits": {"status": "not_run"}}}}
    assert evaluate_quality_gate(shared, policy(metric={"rmse": {"max": 0.3}}))["status"] == "investigate"
    assert evaluate_quality_gate(shared, policy(metric_basis="reported", metric={"rmse": {"max": 0.3}}))["status"] == "pass"
    assert evaluate_quality_gate(shared, policy(privacy={"require_audit": True}))["status"] == "investigate"


@pytest.mark.parametrize("value", [{}, policy(), policy(slices={"critical": {}}), policy(metric={"rmse": {"max": float("nan")}}), policy(metric={"unknown": {"max": 1}}), policy(metric={"rmse": {"max": True}}), policy(privacy={"require_audit": "false"})])
def test_invalid_or_empty_policies_fail_closed(value):
    with pytest.raises(ValueError):
        validate_quality_policy(value)


def test_fail_takes_precedence_over_insufficient_evidence_without_mutating_source():
    source = report()
    original = deepcopy(source)
    result = evaluate_quality_gate(source, policy(metric={"rmse": {"max": 0.1}, "r2": {"min": 0.8}}))
    assert result["status"] == "fail" and source == original
    assert {rule["status"] for rule in result["rules"]} == {"fail", "investigate"}


def test_run_gates_are_bound_to_reports_and_receipts_and_can_be_reproduced(tmp_path, monkeypatch, capsys):
    config = yaml.safe_load(Path("configs/tabular_eval.yaml").read_text())
    config["quality_gate"] = policy(metric={"rmse": {"max": 0.01}})
    config["report"] = {"json": str(tmp_path / "run.json"), "markdown": str(tmp_path / "run.md"), "manifest": str(tmp_path / "run_manifest.json")}
    config["audit"] = {"path": str(tmp_path / "audit.jsonl")}
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config))
    monkeypatch.setattr("sys.argv", ["plb", "run", str(path)])
    assert main() == 1
    local = tmp_path / "run_receipt.json"
    receipt = json.loads(local.read_text())
    assert receipt["local"]["quality_gate"]["status"] == "fail"
    assert verify_run_manifest(tmp_path / "run_manifest.json")["valid"]
    public = json.loads((tmp_path / "run_receipt.shareable.json").read_text())
    assert "quality_gate" not in public["shareable"]["evaluation"]
    policy_path = tmp_path / "quality.yaml"
    policy_path.write_text(yaml.safe_dump(config["quality_gate"]))
    capsys.readouterr()
    monkeypatch.setattr("sys.argv", ["plb", "gate", str(local), "--policy", str(policy_path), "--out", str(tmp_path / "decision.json")])
    assert main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "fail" and result["scope"] == "local"
    assert (tmp_path / "decision.json").exists()
    payload = json.loads(local.read_text())
    payload["local"]["exact_metrics"]["rmse"] = 0
    local.write_text(json.dumps(payload))
    assert main() == 2
    assert not (tmp_path / "decision.json").exists()
