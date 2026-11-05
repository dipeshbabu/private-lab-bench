import csv
import importlib.util
import json
from pathlib import Path

import pytest

from privatelabbench.reports.receipt import verify_receipt

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/first_run.py"
spec = importlib.util.spec_from_file_location("first_run_example", EXAMPLE)
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


@pytest.mark.parametrize("share_synthetic", [False, True])
def test_first_run_computes_a_complete_decision_and_preserves_disclosure_boundary(
    tmp_path, capsys, share_synthetic
):
    output = tmp_path / "synthetic example"
    result = example.run_example(output, share_synthetic=share_synthetic)
    assert result["n_samples"] >= 100
    assert result["paired_interval"]["status"] == "evaluated"
    assert result["paired_interval"]["lower"] > result["practical_improvement"]
    assert result["critical_slice"]["status"] == "fail"
    assert result["critical_slice"]["observed"] > result["critical_slice"]["threshold"]
    assert result["quality_status"] == "fail"
    assert result["independent_researcher_trial"] is False
    assert result["signature_present"] is False
    assert verify_receipt(result["receipt"])["valid"]
    points = {}
    for name in ["candidate", "baseline"]:
        with (output / (name + ".csv")).open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert (
            len({row["sample_id"] for row in rows}) == len(rows) == result["n_samples"]
        )
        points[name] = sum(
            abs(float(row["target"]) - float(row["prediction"])) for row in rows
        ) / len(rows)
    assert result["candidate_mae"] == pytest.approx(points["candidate"])
    assert result["baseline_mae"] == pytest.approx(points["baseline"])
    assert result["paired_improvement"] == pytest.approx(
        points["baseline"] - points["candidate"]
    )
    saved = json.loads((output / "decision.json").read_text(encoding="utf-8"))
    assert saved == result
    public = output / "evaluation/evaluation_receipt.shareable.json"
    assert public.exists() is share_synthetic
    if share_synthetic:
        checked = verify_receipt(public)
        assert checked["valid"] and not checked["signature_present"]
        text = public.read_text(encoding="utf-8")
        assert str(tmp_path) not in text and "synthetic-specimen-" not in text
        assert (
            json.loads(text)["shareable"]["evaluation"]["quality_gate"]["status"]
            == "fail"
        )
    else:
        audit = json.loads(
            public.with_suffix(".release-audit.json").read_text(encoding="utf-8")
        )
        assert audit["decision"] != "allow"
    printed = capsys.readouterr().out
    assert "SYNTHETIC" in printed and "95% CI" in printed and "REJECT" in printed
    assert "no authenticated signer" in printed
    assert "YOUR.csv" in printed and len(printed.splitlines()) <= 12


def test_first_run_rejects_existing_files_before_generation(tmp_path):
    sentinel = tmp_path / "candidate.csv"
    sentinel.write_bytes(b"existing private data")
    with pytest.raises(ValueError, match="existing files are preserved"):
        example.run_example(tmp_path)
    assert list(tmp_path.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"existing private data"
