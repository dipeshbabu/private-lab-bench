import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.caco2_case_study import case_protocol, evaluate_case, write_decision_page


def fixture_data():
    n = 120
    target = np.arange(n, dtype=float) / 10 + 0.125
    units = np.repeat(np.arange(60), 2)
    reference = pd.DataFrame(
        {
            "sample_id": [f"private-sample-{index}" for index in range(n)],
            "target": target,
            "prediction": target + 0.05,
            "baseline": target + 0.3,
            "molecule_unit": [f"PRIVATE_UNIT_{index}" for index in units],
            "regime": np.where(units >= 40, "high-logp", "other"),
            "smiles": "PRIVATE_SMILES_SENTINEL",
        }
    )
    current = reference.copy()
    current["target"] = current.target + np.where(
        current.regime == "high-logp", 0.8, 0.0
    )
    training = pd.DataFrame(
        {
            "sample_id": [f"fit-{index}" for index in range(30)],
            "molecule_unit": [f"training-unit-{index}" for index in range(30)],
        }
    )
    models = {
        "caco2-rf-reference": {
            "schema_version": "synthetic-test-model/v1",
            "coefficient": 1,
        },
        "caco2-training-mean": {
            "schema_version": "synthetic-test-model/v1",
            "coefficient": 0,
        },
    }
    provenance = {
        "data_provenance": "synthetic_test_fixture",
        "description": "Synthetic CI fixture only; not a real public benchmark or independent researcher trial.",
    }
    return reference, current, training, models, provenance


def test_case_decision_release_and_limited_trust_end_to_end(tmp_path):
    result = evaluate_case(tmp_path / "case", *fixture_data(), fixture=True)
    public = result["public_dir"]
    combined = "\n".join(
        path.read_text() for path in public.iterdir() if path.is_file()
    )
    assert (
        "private-sample-" not in combined
        and "PRIVATE_UNIT_" not in combined
        and "PRIVATE_SMILES" not in combined
    )
    assert str(tmp_path) not in combined
    assert all(
        check["valid"]
        and check["signature_valid"]
        and check["signer_trusted"]
        and check["execution_verified"] is False
        for check in result["verification"].values()
    )
    proxy = json.loads((public / "proxy-candidate.json").read_text())
    assert proxy["shareable"]["evaluation"]["quality_gate"]["status"] in {
        "fail",
        "investigate",
    }
    assert proxy["shareable"]["evaluation"]["design_audit"]["status"] == "pass"
    assert (
        proxy["shareable"]["evaluation"]["degradation_summary"]["uncertainty"][
            "independent_cohorts_declared"
        ]
        is False
    )
    assert (tmp_path / "case/local/example-signing-key.pem").exists()
    assert not (public / "example-signing-key.pem").exists()
    assert (
        json.loads((public / "verification.json").read_text())[
            "independent_researcher_trials_completed"
        ]
        == 0
    )
    decision = (public / "decision.md").read_text()
    assert (
        "Overall proxy MAE: 0.283333 meets the predeclared limit 0.600000 "
        "(120 observations; 60 connectivity units): pass."
    ) in decision
    assert (
        "Critical high-logP group MAE: 0.750000 exceeds the predeclared limit "
        "0.700000 (40 observations; 20 connectivity units): fail."
    ) in decision
    assert "Predeclared practical improvement threshold: 0.020000." in decision


def test_fast_fixture_does_not_redefine_the_published_case_protocol():
    production = case_protocol()
    fixture = case_protocol(fixture=True)
    assert production.ref != fixture.ref
    assert production.as_dict()["uncertainty"]["resamples"] == 1000
    assert fixture.as_dict()["uncertainty"]["resamples"] == 100
    assert production.as_dict()["comparison"]["practical_threshold"] == 0.02


def test_checked_in_examples_verify_and_contain_only_approved_artifacts():
    import yaml

    from privatelabbench.reports.integrity import verify_payload

    root = Path(__file__).resolve().parents[1] / "examples/caco2_case/approved"
    assert {path.name for path in root.iterdir()} == {
        "reference-candidate.json",
        "proxy-candidate.json",
        "proxy-baseline.json",
        "proxy-paired.json",
        "trust-store.yaml",
        "decision.md",
        "verification.json",
    }
    trust = yaml.safe_load((root / "trust-store.yaml").read_text())
    for name in (
        "reference-candidate",
        "proxy-candidate",
        "proxy-baseline",
        "proxy-paired",
    ):
        payload = json.loads((root / (name + ".json")).read_text())
        checked = verify_payload(
            payload, trust_store=trust, require_trusted_signer=True
        )
        assert (
            checked["valid"]
            and checked["evidence_level"] == "authenticated_signer_statement"
            and checked["execution_verified"] is False
        )
        assert payload["scope"] == "shareable" and "local" not in payload
        text = json.dumps(payload)
        assert (
            "tdc-caco2_wang-test-" not in text and "D:\\\\private-lab-bench" not in text
        )


def _approved_decision_inputs(tmp_path):
    """Engineering rendering fixture; copies public aggregates, never raw data."""
    source = Path(__file__).resolve().parents[1] / "examples/caco2_case/approved"
    for name in (
        "reference-candidate.json",
        "proxy-candidate.json",
        "proxy-baseline.json",
        "proxy-paired.json",
    ):
        shutil.copyfile(source / name, tmp_path / name)
    return tmp_path


def test_decision_page_explains_approved_numeric_reasons_without_resigning(tmp_path):
    public = _approved_decision_inputs(tmp_path)
    before = {path.name: path.read_bytes() for path in public.glob("*.json")}
    decision = write_decision_page(public, case_protocol()).read_text()
    assert (
        "Overall proxy MAE: 0.604110 exceeds the predeclared limit 0.600000 "
        "(182 observations; 140 connectivity units): fail."
    ) in decision
    assert (
        "Overall proxy MAE interval upper bound: 0.663107 meets the "
        "predeclared limit 0.700000: pass."
    ) in decision
    assert (
        "Critical high-logP group MAE: 0.849552 exceeds the predeclared limit "
        "0.700000 (61 observations; 59 connectivity units): fail."
    ) in decision
    assert "Paired improvement of candidate over baseline: 0.130868." in decision
    assert (
        "Paired interval: [0.071865, 0.191472]; its lower bound meets the "
        "predeclared practical improvement criterion (at least 0.020000)."
    ) in decision
    assert "Relative improvement does not waive" in decision
    assert before == {path.name: path.read_bytes() for path in public.glob("*.json")}
    source = Path(__file__).resolve().parents[1] / "examples/caco2_case/approved"
    assert decision == (source / "decision.md").read_text()


@pytest.mark.parametrize(
    ("lower", "expected"),
    [(0.019999, "does not meet"), (0.02, "meets"), (0.020001, "meets")],
    ids=["below-threshold", "equal-to-threshold", "above-threshold"],
)
def test_decision_page_paired_interval_positive_threshold_boundary(
    tmp_path, lower, expected
):
    """Synthetic interval boundaries use the unchanged public 0.02 rule."""
    public = _approved_decision_inputs(tmp_path)
    path = public / "proxy-paired.json"
    receipt = json.loads(path.read_text())
    receipt["shareable"]["paired_interval"]["lower"] = lower
    path.write_text(json.dumps(receipt))
    protocol = case_protocol()
    assert protocol.as_dict()["comparison"]["practical_threshold"] == 0.02
    decision = write_decision_page(public, protocol).read_text()
    interval = next(
        line for line in decision.splitlines() if line.startswith("Paired interval:")
    )
    assert f"[{lower:.6f}, 0.191472]" in interval
    assert (
        f"its lower bound {expected} the predeclared practical improvement "
        "criterion (at least 0.020000)."
    ) in interval


@pytest.mark.parametrize(
    "missing",
    ["slice", "metric", "null", "nonfinite", "unavailable_status"],
)
def test_decision_page_does_not_pass_unavailable_critical_evidence(tmp_path, missing):
    """Synthetic suppression/missing-value cases exercise explanation behavior."""
    public = _approved_decision_inputs(tmp_path)
    path = public / "proxy-candidate.json"
    receipt = json.loads(path.read_text())
    regime = receipt["shareable"]["evaluation"]["slices"]["regime"]
    if missing == "slice":
        del regime["high-logp"]
    elif missing == "metric":
        regime["high-logp"]["metrics"].pop("mae")
    elif missing == "unavailable_status":
        regime["high-logp"].update(status="suppressed")
        regime["high-logp"]["metrics"]["mae"] = 0.1
    else:
        regime["high-logp"]["metrics"]["mae"] = (
            None if missing == "null" else float("nan")
        )
    path.write_text(json.dumps(receipt))
    decision = write_decision_page(public, case_protocol()).read_text()
    critical = next(
        line for line in decision.splitlines() if line.startswith("Critical high-logP")
    )
    assert "unavailable; predeclared limit 0.700000" in critical
    assert critical.endswith(": investigate.")
    assert ": pass." not in critical


def test_decision_page_rejects_different_public_rules(tmp_path):
    public = _approved_decision_inputs(tmp_path)
    with pytest.raises(ValueError, match="approved protocol digest"):
        write_decision_page(public, case_protocol(fixture=True))
    assert not (public / "decision.md").exists()
