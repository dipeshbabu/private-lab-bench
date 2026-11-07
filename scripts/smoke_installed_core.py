"""Exercise an installed distribution outside the checkout, with synthetic data only."""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing
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


def _held_export(candidate, policy, output, ready, resume, result):
    import privatelabbench.privacy.export as exports

    original = exports.atomic_write_json

    def write(path, value):
        original(path, value)
        if path == output:
            ready.set()
            if not resume.wait(60):
                raise RuntimeError("Installed publisher checkpoint timed out")

    exports.atomic_write_json = write
    try:
        result.put(
            exports.publish_shareable_artifact(candidate, policy, output).decision
        )
    finally:
        exports.atomic_write_json = original


def check_installed_export_transaction(receipt, folder):
    import privatelabbench.privacy.export as exports

    candidate = json.loads(receipt.read_text(encoding="utf-8"))
    policy = {
        "schema_version": "release-policy/v1",
        "id": "synthetic-installed-regression",
        "enabled": True,
        "min_samples": 20,
        "min_cell_size": 20,
        "require_privacy_audit": False,
    }
    output = folder / "publisher/receipt.shareable.json"
    context = multiprocessing.get_context("spawn")
    ready, resume, result = context.Event(), context.Event(), context.Queue()
    worker = context.Process(
        target=_held_export, args=(candidate, policy, output, ready, resume, result)
    )
    worker.start()
    try:
        assert ready.wait(60), "Installed publisher did not reach its checkpoint"
        content = output.read_bytes()
        assert (
            exports.publish_shareable_artifact(candidate, policy, output).decision
            == "needs_review"
        )
        assert output.read_bytes() == content
    finally:
        resume.set()
        worker.join(60)
        if worker.is_alive():
            worker.terminate()
            worker.join()
    assert worker.exitcode == 0 and result.get(timeout=10) == "allow"
    result.close()
    result.join_thread()
    assert output.exists() and verify_receipt(output)["valid"]
    assert (
        json.loads(
            output.with_suffix(".release-audit.json").read_text(encoding="utf-8")
        )["decision"]
        == "allow"
    )


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
    parser.add_argument("--require-plugin", action="store_true")
    args = parser.parse_args()
    assert (
        version("private-lab-bench")
        == privatelabbench.__version__
        == args.expected_version
    )
    assert "site-packages" in Path(privatelabbench.__file__).parts
    if "t" in getattr(sys, "abiflags", ""):
        assert not sys._is_gil_enabled(), "A core dependency re-enabled the GIL"
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
    check_installed_export_transaction(receipt, folder)
    malformed = folder / "malformed-receipt.json"
    malformed.write_text(json.dumps({"scope": "local", "local": []}), encoding="utf-8")
    release_policy = folder / "release-policy.json"
    release_policy.write_text(
        json.dumps(
            {"schema_version": "release-policy/v1", "id": "synthetic", "enabled": False}
        ),
        encoding="utf-8",
    )
    rejected = cli("release-check", malformed, "--policy", release_policy, expected=1)
    assert "unreadable_policy_or_artifact" in rejected and "Traceback" not in rejected
    checks.append(
        "installed concurrent publisher and malformed release-check regressions"
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

    if args.require_plugin:
        assert version("plb-ci-task-plugin") == "0.0.1"
        assert "ci-installed-plugin" in cli("list-tasks")
        config = folder / "plugin.yaml"
        plugin_output = folder / "plugin-results"
        config.write_text(
            yaml.safe_dump(
                {
                    "project": "synthetic-plugin",
                    "task": "ci-installed-plugin",
                    "input": {
                        "path": str(candidate),
                        "target_column": "target",
                        "prediction_column": "prediction",
                        "sample_id_column": "sample_id",
                        "task_type": "regression",
                    },
                    "report": {
                        "json": str(plugin_output / "evaluation.json"),
                        "markdown": str(plugin_output / "evaluation.md"),
                        "manifest": str(plugin_output / "evaluation_manifest.json"),
                    },
                    "audit": {"path": str(plugin_output / "audit.jsonl")},
                    "privacy": {"mode": "none"},
                }
            ),
            encoding="utf-8",
        )
        cli("run", config)
        plugin_receipt = plugin_output / "evaluation_receipt.json"
        cli("verify", plugin_receipt)
        assert verify_receipt(plugin_receipt)["valid"]
        plugin_report = json.loads(
            (plugin_output / "evaluation.json").read_text(encoding="utf-8")
        )
        assert abs(plugin_report["result"]["clean_metrics"]["mae"] - 0.1) < 1e-12
        checks.append(
            "actual installed third-party entry point, execution, and receipt"
        )

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
