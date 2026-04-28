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
    config_path.write_text(
        f"""
project: test-prediction
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
""".strip()
    )
    summary = run_config(str(config_path))
    assert summary["workflow"] == "predictions"
    assert md_path.exists()
    assert json_path.exists()
    payload = json.loads(json_path.read_text())
    assert payload["report_type"] == "prediction_evaluation"


def test_molecule_runner_writes_reports(tmp_path):
    config_path = tmp_path / "molecule_eval.yaml"
    md_path = tmp_path / "molecule.md"
    json_path = tmp_path / "molecule.json"
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
""".strip()
    )
    summary = run_config(str(config_path))
    assert summary["workflow"] == "molecules"
    assert md_path.exists()
    assert json_path.exists()


def test_federated_runner_writes_reports(tmp_path):
    config_path = tmp_path / "federated_eval.yaml"
    md_path = tmp_path / "federated.md"
    json_path = tmp_path / "federated.json"
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
""".strip()
    )
    summary = run_config(str(config_path))
    assert summary["workflow"] == "federated"
    assert summary["n_clients"] == 3
    assert md_path.exists()
    assert json_path.exists()
