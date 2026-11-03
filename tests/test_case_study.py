import json
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.caco2_case_study import evaluate_case, case_protocol


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
