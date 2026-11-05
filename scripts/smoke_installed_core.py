"""Exercise an installed distribution outside the checkout, with synthetic data only."""

from __future__ import annotations

import argparse
import csv
import json
import platform
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import numpy as np
import yaml

import privatelabbench
from privatelabbench.eval.metrics import multiclass_metrics
from privatelabbench.privacy.attacks import membership_inference_risk
from privatelabbench.privacy.export import publish_shareable_artifact
from privatelabbench.reports.integrity import attach_integrity_metadata, verify_payload
from privatelabbench.reports.receipt import verify_receipt


def cli(*args, expected=0):
    result = subprocess.run(
        [sys.executable, "-m", "privatelabbench.cli", *map(str, args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    if result.returncode != expected:
        raise RuntimeError(
            f"CLI returned {result.returncode}, expected {expected}: {result.stdout}\n{result.stderr}"
        )
    return result.stdout + result.stderr


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args()
    assert (
        version("private-lab-bench")
        == privatelabbench.__version__
        == args.expected_version
    )
    assert "site-packages" in Path(privatelabbench.__file__).parts
    root = Path.cwd()
    checks = []
    assert "usage:" in cli("--help").lower()
    assert "community-tabular-regression@1.0.0" in cli("list-packs")
    cli("run-pack", "community-tabular-regression@1.0.0")
    cli("verify", "reports/benchmark_packs/tabular_regression_receipt.shareable.json")
    checks.append("installed CLI and bundled package data")

    folder = root / "mesures 測試"
    folder.mkdir()
    candidate, baseline = folder / "candidat.csv", folder / "référence.csv"
    for path, error in [(candidate, 0.1), (baseline, 0.4)]:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["sample_id", "target", "prediction", "instrument"])
            for index in range(48):
                value = index / 10 + 0.125
                writer.writerow(
                    [
                        f"{index:03d}",
                        value,
                        value + error,
                        "lab-α" if index < 24 else "lab-β",
                    ]
                )
    output = folder / "résultats"
    cli(
        "evaluate",
        candidate,
        "--task-type",
        "regression",
        "--primary-metric",
        "mae",
        "--slice",
        "instrument",
        "--resamples",
        100,
        "--output-dir",
        output,
    )
    receipt = output / "evaluation_receipt.json"
    cli("verify", receipt)
    assert verify_receipt(receipt)["valid"]
    assert not (output / "evaluation_receipt.shareable.json").exists()
    report = json.loads((output / "evaluation.json").read_text(encoding="utf-8"))[
        "result"
    ]
    assert abs(report["clean_metrics"]["mae"] - 0.1) < 1e-12
    assert report["uncertainty"]["status"] == "evaluated"
    assert set(report["slice_metrics"]["instrument"]) == {"lab-α", "lab-β"}
    assert all(
        group["status"] == "evaluated"
        for group in report["slice_metrics"]["instrument"].values()
    )
    checks.append(
        "Unicode paths, CSV/newline handling, uncertainty, slices, local receipt"
    )

    paired = folder / "comparaison.json"
    cli(
        "compare",
        candidate,
        baseline,
        "--target",
        "target",
        "--task-type",
        "regression",
        "--metric",
        "mae",
        "--resamples",
        100,
        "--permutations",
        0,
        "--report",
        folder / "comparaison.md",
        "--json-report",
        paired,
    )
    cli("verify", paired)
    comparison = json.loads(paired.read_text(encoding="utf-8"))["shareable"]
    assert comparison["paired_interval"]["status"] == "evaluated"
    assert abs(comparison["improvement_a_over_b"] - 0.3) < 1e-12
    checks.append("paired comparison and artifact verification")

    policy = folder / "quality.yaml"
    policy.write_text(
        yaml.safe_dump(
            {"schema_version": "quality-policy/v1", "metric": {"mae": {"max": 0.05}}}
        ),
        encoding="utf-8",
    )
    cli("gate", receipt, "--policy", policy, expected=1)
    assert "unrecognized arguments" in cli(
        "evaluate", candidate, "--unknown-option", expected=2
    )
    checks.append("quality-gate and argparse exit codes")

    before = candidate.read_bytes()
    alias = folder / "alias.csv"
    alias.hardlink_to(candidate)
    cli(
        "eval-predictions",
        candidate,
        "--target",
        "target",
        "--prediction-column",
        "prediction",
        "--report",
        alias,
        expected=2,
    )
    assert alias.read_bytes() == candidate.read_bytes() == before
    cli(
        "init",
        candidate,
        "--task-type",
        "regression",
        "--out",
        alias,
        "--force",
        expected=2,
    )
    assert alias.read_bytes() == candidate.read_bytes() == before
    ledger = folder / ".plb-release-ledger.json"
    ledger.write_bytes(b"existing local release state")
    try:
        publish_shareable_artifact({}, None, ledger)
    except ValueError:
        pass
    else:
        raise AssertionError("Reserved release state was accepted as an output")
    assert ledger.read_bytes() == b"existing local release state"
    checks.append("hard-link preservation and reserved release-state paths")

    result = multiclass_metrics(np.array([30, 10, 20]), np.eye(3), labels=[30, 10, 20])
    assert result["accuracy"] == result["macro_auroc_ovr"] == 1.0
    audit = membership_inference_risk(
        train_y=np.zeros(30),
        train_score=np.ones(30),
        test_y=np.zeros(10),
        test_score=np.ones(10),
        task_type="regression",
    )
    assert audit["member_advantage"] == 0 and audit["attack_auc"] == 0.5
    payload = attach_integrity_metadata({"scope": "local"})
    payload["integrity"]["payload_sha256"] = "é" * 64
    assert verify_payload(payload)["valid"] is False
    checks.append(
        "custom class labels, balanced membership risk, malformed digest rejection"
    )

    summary = {
        "platform": platform.system(),
        "python": platform.python_version(),
        "package": privatelabbench.__version__,
        "installed_from_site_packages": True,
        "dependencies": {
            name: version(name)
            for name in ["numpy", "pandas", "scikit-learn", "scipy", "PyYAML"]
        },
        "checks": checks,
    }
    (root / "smoke-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == "__main__":
    main()
