from pathlib import Path

import pandas as pd

from privatelabbench.adapters.sklearn_adapter import RandomForestMoleculeAdapter
from privatelabbench.compare import compare_configs
from privatelabbench.tasks.molecules import load_molecule_csv


def test_random_forest_adapter_returns_error_slices(tmp_path: Path):
    csv_path = tmp_path / "molecules.csv"
    pd.DataFrame(
        {
            "smiles": ["CCO", "CCN", "CCC", "c1ccccc1", "CCCl", "CCBr", "COC", "CC=O"],
            "label": [1, 1, 0, 0, 1, 0, 1, 0],
        }
    ).to_csv(csv_path, index=False)

    dataset = load_molecule_csv(str(csv_path), target="label", task_type="classification")
    result = RandomForestMoleculeAdapter(n_estimators=10, n_bits=64).evaluate(dataset, test_size=0.25, seed=7)

    assert result["adapter"] == "random_forest_hashed"
    assert result["fingerprint"] == "hashed_smiles"
    assert "error_slices" in result
    assert "error_rate" in result["error_slices"]


def test_compare_configs_generates_reports(tmp_path: Path):
    pred_path = tmp_path / "predictions.csv"
    pd.DataFrame({"label": [1, 0, 1, 0], "pred": [0.9, 0.2, 0.7, 0.1]}).to_csv(pred_path, index=False)

    cfg1 = tmp_path / "pred1.yaml"
    cfg1.write_text(
        f"""
project: pred_one
workflow: predictions
input:
  path: {pred_path}
  target_column: label
  prediction_column: pred
  task_type: classification
report:
  markdown: {tmp_path / 'pred1.md'}
  json: {tmp_path / 'pred1.json'}
audit:
  path: {tmp_path / 'pred1_audit.jsonl'}
""".strip(),
        encoding="utf-8",
    )
    cfg2 = tmp_path / "pred2.yaml"
    cfg2.write_text(cfg1.read_text(encoding="utf-8").replace("pred_one", "pred_two").replace("pred1", "pred2"), encoding="utf-8")

    out_md = tmp_path / "compare.md"
    out_json = tmp_path / "compare.json"
    result = compare_configs([str(cfg1), str(cfg2)], markdown_path=str(out_md), json_path=str(out_json))

    assert result["n_runs"] == 2
    assert out_md.exists()
    assert out_json.exists()
