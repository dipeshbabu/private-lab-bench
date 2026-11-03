import json

import pandas as pd
import pytest

from privatelabbench.benchmark_packs import get_benchmark_pack, run_benchmark_pack


def test_bundled_pack_uses_its_fixture_when_cwd_has_predictions(tmp_path, monkeypatch):
    pack = get_benchmark_pack("community-tabular-regression@1.0.0")
    shadow = pd.read_csv(pack.config_path.parent / "predictions.csv")
    shadow["target"] += 100
    shadow["sample_id"] = [f"local-private-{index}" for index in range(len(shadow))]
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "predictions.csv"
    shadow.to_csv(path, index=False)
    original = path.read_bytes()

    summary = run_benchmark_pack(pack.ref)

    expected = json.loads(pack.expected_receipt_path.read_text(encoding="utf-8"))
    assert summary["clean_metrics"] == pytest.approx(
        expected["shareable"]["evaluation"]["metrics"]
    )
    assert path.read_bytes() == original
    receipt = (
        tmp_path / "reports/benchmark_packs/tabular_regression_receipt.shareable.json"
    )
    published = json.loads(receipt.read_text(encoding="utf-8"))
    assert published["shareable"]["evaluation"]["metrics"] == pytest.approx(
        summary["clean_metrics"]
    )
    assert "local-private" not in receipt.read_text(encoding="utf-8")
