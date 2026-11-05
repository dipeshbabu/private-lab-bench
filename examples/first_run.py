"""A fully synthetic model-selection walkthrough using the installed library.

No model training, external data, account, or upload is involved. The fixture is
constructed to improve overall while failing a prespecified instrument requirement.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path

import yaml

from privatelabbench.compare import compare_prediction_files
from privatelabbench.evaluate import make_evaluation_config
from privatelabbench.privacy.export import atomic_write_json
from privatelabbench.reports.receipt import verify_receipt
from privatelabbench.runner import run_config

N_SAMPLES = 160
PRACTICAL_IMPROVEMENT = 0.05
QUALITY_POLICY = {
    "schema_version": "quality-policy/v1",
    "min_samples": 20,
    "metric": {"mae": {"max": 0.35, "max_ci_upper": 0.40}},
    "slices": {
        "critical": {
            "instrument_b": {
                "column": "instrument",
                "value": "instrument-b",
                "metric": "mae",
                "max": 0.50,
            }
        }
    },
}


def write_fixture(output: Path) -> tuple[Path, Path]:
    """Independent simulated specimens; instrument B has a fixed calibration bias."""
    rng = random.Random(20261105)
    candidate, baseline = output / "candidate.csv", output / "baseline.csv"
    with (
        candidate.open("w", encoding="utf-8", newline="") as first,
        baseline.open("w", encoding="utf-8", newline="") as second,
    ):
        a, b = csv.writer(first), csv.writer(second)
        header = ["sample_id", "target", "prediction", "instrument"]
        a.writerow(header)
        b.writerow(header)
        for index in range(N_SAMPLES):
            instrument = "instrument-a" if index < 120 else "instrument-b"
            signal = 0.2 + index / 100 + math.sin(index / 7) / 4
            target = signal + rng.gauss(0, 0.04)
            predicted = signal + (0.10 if index < 120 else 0.80) + rng.gauss(0, 0.03)
            reference = signal + 0.50 + rng.gauss(0, 0.06)
            identity = f"synthetic-specimen-{index:03d}"
            a.writerow([identity, f"{target:.8f}", f"{predicted:.8f}", instrument])
            b.writerow([identity, f"{target:.8f}", f"{reference:.8f}", instrument])
    return candidate, baseline


def run_example(output_dir: str | Path, *, share_synthetic: bool = False) -> dict:
    output = Path(output_dir).resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(
            "Choose a new or empty output directory; existing files are preserved"
        )
    output.mkdir(parents=True, exist_ok=True)
    # Thresholds are fixed above, before generating or examining the fixture.
    (output / "quality.yaml").write_text(
        yaml.safe_dump(QUALITY_POLICY), encoding="utf-8"
    )
    candidate, baseline = write_fixture(output)
    release = None
    if share_synthetic:
        release = {
            "schema_version": "release-policy/v1",
            "id": "synthetic-first-run-v1",
            "enabled": True,
            "min_samples": 20,
            "min_cell_size": 20,
            "require_privacy_audit": False,
            "include_quality_gate": True,
            "slices": {"instrument": ["instrument-a", "instrument-b"]},
        }
        (output / "synthetic-release.yaml").write_text(
            yaml.safe_dump(release), encoding="utf-8"
        )
    settings = make_evaluation_config(
        candidate,
        output_dir=output / "evaluation",
        task_type="regression",
        primary_metric="mae",
        slices=["instrument"],
        min_slice_size=20,
        quality_policy=QUALITY_POLICY,
        release_policy=release,
        uncertainty={
            "resamples": 1000,
            "confidence_level": 0.95,
            "include_slices": True,
        },
    )
    config = output / "evaluation.yaml"
    config.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
    evaluation = run_config(str(config))
    compared = compare_prediction_files(
        str(candidate),
        str(baseline),
        target="target",
        prediction_column="prediction",
        prediction_columns=None,
        sample_id_column="sample_id",
        task_type="regression",
        class_labels=None,
        slice_columns=["instrument"],
        model_a_name="candidate",
        model_b_name="baseline",
        metric="mae",
        confidence_level=0.95,
        resamples=1000,
        permutations=0,
        seed=13,
        min_samples=20,
        practical_threshold=PRACTICAL_IMPROVEMENT,
        noninferiority_margin=None,
        include_slice_uncertainty=True,
        min_slice_size=20,
        markdown_path=str(output / "paired.md"),
        json_path=str(output / "paired.json"),
        release_policy=release,
    )
    gate = evaluation["quality_gate"]
    critical = next(
        rule for rule in gate["rules"] if rule["name"] == "slice.instrument_b.max"
    )
    interval = compared["paired_interval"]
    slices = compared["slices"]["instrument"]
    if (
        interval["status"] != "evaluated"
        or interval["lower"] <= PRACTICAL_IMPROVEMENT
        or gate["status"] != "fail"
        or critical["status"] != "fail"
        or any(
            group.get("status") != "evaluated"
            or group.get("paired_interval", {}).get("status") != "evaluated"
            for group in slices.values()
        )
    ):
        raise RuntimeError(
            "The synthetic demonstration did not produce complete expected evidence"
        )
    local_receipt = output / "evaluation/evaluation_receipt.json"
    public_receipt = output / "evaluation/evaluation_receipt.shareable.json"
    verified = verify_receipt(local_receipt)
    if not verified["valid"]:
        raise RuntimeError("Local receipt integrity verification failed")
    if share_synthetic and (
        not public_receipt.exists() or not verify_receipt(public_receipt)["valid"]
    ):
        raise RuntimeError(
            "The explicit synthetic export policy did not produce a valid receipt"
        )
    summary = {
        "schema_version": "synthetic-first-run/v1",
        "scope": "local",
        "data_provenance": "fully_synthetic_instrument_calibration_example",
        "n_samples": compared["n_samples"],
        "inferential_unit": "independent_simulated_specimen",
        "candidate_mae": compared["model_a"]["selected_metric"],
        "baseline_mae": compared["model_b"]["selected_metric"],
        "paired_improvement": compared["improvement_a_over_b"],
        "paired_interval": interval,
        "practical_improvement": PRACTICAL_IMPROVEMENT,
        "critical_slice": {"instrument": "instrument-b", **critical},
        "quality_status": gate["status"],
        "decision": "reject_for_instrument_b",
        "release": "explicit_synthetic_policy"
        if public_receipt.exists()
        else "local_only",
        "receipt": str(local_receipt),
        "shareable_receipt": str(public_receipt) if public_receipt.exists() else None,
        "signature_present": bool(verified.get("signature_present")),
        "independent_researcher_trial": False,
    }
    atomic_write_json(output / "decision.json", summary)
    print(
        "SYNTHETIC example: 160 independent simulated specimens; no biological validation claim."
    )
    print(
        f"Candidate MAE {summary['candidate_mae']:.3f}; baseline MAE {summary['baseline_mae']:.3f} (lower is better)."
    )
    print(
        f"Paired improvement {summary['paired_improvement']:.3f}; 95% CI [{interval['lower']:.3f}, {interval['upper']:.3f}]; required improvement {PRACTICAL_IMPROVEMENT:.2f}."
    )
    print(
        f"Instrument B MAE {critical['observed']:.3f} exceeds the prespecified maximum {critical['threshold']:.2f}."
    )
    print(
        "Decision: REJECT for instrument B despite the overall improvement; quality gate FAIL."
    )
    print(
        "Uncertainty assumes independent simulated specimens; real repeated measurements need an appropriate sampling design."
    )
    print(f"Local decision: {output / 'decision.json'}")
    print(f"Local receipt: {local_receipt}")
    print(
        f"Synthetic shareable receipt: {public_receipt}"
        if public_receipt.exists()
        else "Release: LOCAL ONLY; no shareable receipt was approved."
    )
    print(
        "Verification checks integrity. These receipts have no authenticated signer and do not verify execution or scientific validity."
    )
    print(
        "Next: plb evaluate YOUR.csv --task-type regression --slice instrument --output-dir YOUR_RESULTS"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("plb-first-run"))
    parser.add_argument(
        "--share-synthetic",
        action="store_true",
        help="Approve aggregate export for this generated synthetic fixture only",
    )
    args = parser.parse_args()
    try:
        run_example(args.output_dir, share_synthetic=args.share_synthetic)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, f"Example rejected: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
