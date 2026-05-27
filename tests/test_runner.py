import json

from privatelabbench.config import load_config
from privatelabbench.runner import run_config


def test_load_prediction_config():
    config = load_config("configs/prediction_eval.yaml")
    assert config.project == "kinase-prediction-demo"
    assert config.workflow == "predictions"


def test_prediction_runner_writes_reports(tmp_path):
    config_path = tmp_path / "prediction_eval.yaml"
    md_path = tmp_path / "prediction.md"
    json_path = tmp_path / "prediction.json"
    manifest_path = tmp_path / "prediction_manifest.json"
    audit_path = tmp_path / "audit.jsonl"
    config_path.write_text(
        f"""
project: test-prediction
workflow: predictions
benchmark:
  id: kinase-private-v1
  version: "2026.05"
  suite: molecular-property
  domain: molecules
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
  manifest: {manifest_path}
audit:
  path: {audit_path}
""".strip()
    )
    summary = run_config(str(config_path))
    assert summary["workflow"] == "predictions"
    assert md_path.exists()
    assert json_path.exists()
    assert manifest_path.exists()
    assert audit_path.exists()
    payload = json.loads(json_path.read_text())
    assert payload["report_type"] == "prediction_evaluation"
    assert payload["config_snapshot"]["project"] == "test-prediction"
    assert payload["extra"]["benchmark_id"] == "kinase-private-v1"
    assert payload["extra"]["benchmark_version"] == "2026.05"
    assert summary["benchmark_id"] == "kinase-private-v1"
    assert summary["run_id"] == payload["run_id"]
    assert summary["report_payload_sha256"] == payload["integrity"]["payload_sha256"]
    assert summary["manifest"] == str(manifest_path)
    assert payload["integrity"]["payload_sha256"]
    manifest = json.loads(manifest_path.read_text())
    assert manifest["run"]["run_id"] == payload["run_id"]
    assert manifest["benchmark"]["id"] == "kinase-private-v1"
    assert {artifact["kind"] for artifact in manifest["artifacts"]} == {
        "audit_log",
        "config",
        "json_report",
        "markdown_report",
    }


def test_prediction_runner_resolves_input_relative_to_config_file(tmp_path):
    csv_path = tmp_path / "predictions.csv"
    config_path = tmp_path / "prediction_eval.yaml"
    md_path = tmp_path / "prediction.md"
    json_path = tmp_path / "prediction.json"
    manifest_path = tmp_path / "prediction_manifest.json"
    csv_path.write_text(
        "label,pred\n0.1,0.1\n0.2,0.25\n0.3,0.28\n0.4,0.39\n",
        encoding="utf-8",
    )
    config_path.write_text(
        f"""
project: relative-prediction
workflow: predictions
input:
  path: predictions.csv
  target_column: label
  prediction_column: pred
  task_type: regression
privacy:
  mode: none
report:
  markdown: {md_path}
  json: {json_path}
  manifest: {manifest_path}
""".strip(),
        encoding="utf-8",
    )

    summary = run_config(str(config_path))

    assert summary["workflow"] == "predictions"
    assert summary["n_samples"] == 4
    assert json_path.exists()
    assert manifest_path.exists()


def test_prediction_runner_writes_privacy_risk_when_split_column_is_configured(tmp_path):
    csv_path = tmp_path / "predictions_with_split.csv"
    config_path = tmp_path / "prediction_eval.yaml"
    md_path = tmp_path / "prediction.md"
    json_path = tmp_path / "prediction.json"
    manifest_path = tmp_path / "prediction_manifest.json"
    csv_path.write_text(
        "\n".join(
            [
                "label,pred,split",
                "0.10,0.10,train",
                "0.20,0.21,train",
                "0.80,0.78,member",
                "0.90,0.88,1",
                "0.10,0.45,test",
                "0.20,0.52,holdout",
                "0.80,0.51,nonmember",
                "0.90,0.48,0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    config_path.write_text(
        f"""
project: test-prediction-risk
workflow: predictions
input:
  path: {csv_path}
  target_column: label
  prediction_column: pred
  split_column: split
  task_type: regression
privacy:
  mode: none
report:
  markdown: {md_path}
  json: {json_path}
  manifest: {manifest_path}
""".strip(),
        encoding="utf-8",
    )

    summary = run_config(str(config_path))

    assert summary["privacy_risk_level"] in {"moderate", "high"}
    assert summary["privacy_member_advantage"] > 0
    assert "Privacy attack risk" in md_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["result"]["split_column"] == "split"
    assert payload["result"]["privacy_risk"]["attack"] == "loss_threshold_membership_inference"


def test_molecule_runner_writes_reports(tmp_path):
    config_path = tmp_path / "molecule_eval.yaml"
    md_path = tmp_path / "molecule.md"
    json_path = tmp_path / "molecule.json"
    manifest_path = tmp_path / "molecule_manifest.json"
    config_path.write_text(
        f"""
project: test-molecule
workflow: molecules
input:
  path: examples/molecules_demo.csv
  target_column: label
  smiles_column: smiles
  task_type: regression
privacy:
  mode: none
  seed: 13
report:
  markdown: {md_path}
  json: {json_path}
  manifest: {manifest_path}
""".strip()
    )
    summary = run_config(str(config_path))
    assert summary["workflow"] == "molecules"
    assert md_path.exists()
    assert json_path.exists()
    assert manifest_path.exists()


def test_federated_runner_writes_reports(tmp_path):
    config_path = tmp_path / "federated_eval.yaml"
    md_path = tmp_path / "federated.md"
    json_path = tmp_path / "federated.json"
    manifest_path = tmp_path / "federated_manifest.json"
    config_path.write_text(
        f"""
project: test-federated
workflow: federated
input:
  client_dir: examples/labs
  target_column: label
  smiles_column: smiles
  task_type: regression
privacy:
  mode: none
  seed: 13
report:
  markdown: {md_path}
  json: {json_path}
  manifest: {manifest_path}
""".strip()
    )
    summary = run_config(str(config_path))
    assert summary["workflow"] == "federated"
    assert summary["n_clients"] == 3
    assert md_path.exists()
    assert json_path.exists()
    assert manifest_path.exists()
