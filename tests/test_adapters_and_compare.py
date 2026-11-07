from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from privatelabbench.adapters.sklearn_adapter import RandomForestMoleculeAdapter
from privatelabbench.compare import compare_configs
from privatelabbench.tasks.molecules import load_molecule_csv


def test_morgan_adapter_matches_rdkit_bits_and_handles_empty_and_invalid_inputs():
    pytest.importorskip("rdkit")
    from rdkit import Chem, DataStructs
    from rdkit.Chem import rdFingerprintGenerator

    from privatelabbench.adapters.fingerprints import RDKitMorganFingerprintAdapter

    adapter = RDKitMorganFingerprintAdapter(radius=2, n_bits=128)
    actual = adapter.transform(["CCO", "c1ccccc1", "CCO"])
    expected = np.zeros((3, 128), dtype=np.float32)
    generator = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=128)
    for row, smiles in zip(expected, ["CCO", "c1ccccc1", "CCO"]):
        DataStructs.ConvertToNumpyArray(
            generator.GetFingerprint(Chem.MolFromSmiles(smiles)), row
        )
    np.testing.assert_array_equal(actual, expected)
    assert actual.dtype == np.float32
    assert adapter.transform([]).shape == (0, 128)
    with pytest.raises(ValueError, match="could not parse"):
        adapter.transform(["not a molecule"])


def test_morgan_random_forest_uses_the_optional_adapter(tmp_path):
    pytest.importorskip("rdkit")
    source = tmp_path / "molecules.csv"
    pd.DataFrame(
        {
            "smiles": ["CCO", "CCN", "CCC", "COC", "CCCl", "CCBr", "CC=O", "c1ccccc1"],
            "label": [0.1, 0.2, 0.4, 0.3, 0.7, 0.6, 0.8, 0.9],
        }
    ).to_csv(source, index=False)
    dataset = load_molecule_csv(str(source), target="label", task_type="regression")
    result = RandomForestMoleculeAdapter(
        fingerprint="rdkit_morgan", n_bits=64, n_estimators=10
    ).evaluate(dataset, seed=7)
    assert result["fingerprint"] == "rdkit_morgan"
    assert result["n_train"] + result["n_test"] == 8
    assert all(np.isfinite(value) for value in result["metrics"].values())


def test_random_forest_adapter_returns_error_slices(tmp_path: Path):
    csv_path = tmp_path / "molecules.csv"
    pd.DataFrame(
        {
            "smiles": ["CCO", "CCN", "CCC", "c1ccccc1", "CCCl", "CCBr", "COC", "CC=O"],
            "label": [1, 1, 0, 0, 1, 0, 1, 0],
        }
    ).to_csv(csv_path, index=False)

    dataset = load_molecule_csv(
        str(csv_path), target="label", task_type="classification"
    )
    result = RandomForestMoleculeAdapter(n_estimators=10, n_bits=64).evaluate(
        dataset, test_size=0.25, seed=7
    )

    assert result["adapter"] == "random_forest_hashed"
    assert result["fingerprint"] == "hashed_smiles"
    assert "error_slices" in result
    assert "error_rate" in result["error_slices"]


def test_compare_configs_generates_reports(tmp_path: Path):
    pred_path = tmp_path / "predictions.csv"
    pd.DataFrame({"label": [1, 0, 1, 0], "pred": [0.9, 0.2, 0.7, 0.1]}).to_csv(
        pred_path, index=False
    )

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
  markdown: {tmp_path / "pred1.md"}
  json: {tmp_path / "pred1.json"}
audit:
  path: {tmp_path / "pred1_audit.jsonl"}
""".strip(),
        encoding="utf-8",
    )
    cfg2 = tmp_path / "pred2.yaml"
    cfg2.write_text(
        cfg1.read_text(encoding="utf-8")
        .replace("pred_one", "pred_two")
        .replace("pred1", "pred2"),
        encoding="utf-8",
    )

    out_md = tmp_path / "compare.md"
    out_json = tmp_path / "compare.json"
    result = compare_configs(
        [str(cfg1), str(cfg2)], markdown_path=str(out_md), json_path=str(out_json)
    )

    assert result["n_runs"] == 2
    assert out_md.exists()
    assert out_json.exists()
