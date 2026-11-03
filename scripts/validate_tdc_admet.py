"""Opt-in real TDC parity run; downloads stay outside tracked source."""

from __future__ import annotations

import argparse
from importlib.metadata import version, PackageNotFoundError
import json
from pathlib import Path

import numpy as np
import pandas as pd

from privatelabbench.integrations.tdc import (
    ARCHIVE_ID,
    ARCHIVE_SHA256,
    SOURCE_URL,
    TASKS,
    download_benchmarks,
    evaluate_tdc,
    load_benchmark,
    partition_table,
    _write_csv,
)
from privatelabbench.privacy.export import atomic_write_json
from privatelabbench.reports.receipt import verify_receipt


def fingerprints(smiles):
    from rdkit import Chem, DataStructs
    from rdkit.Chem import rdFingerprintGenerator

    generator = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
    values = np.empty((len(smiles), 2048), dtype=np.uint8)
    for index, value in enumerate(smiles):
        molecule = Chem.MolFromSmiles(str(value))
        if molecule is None:
            raise ValueError(
                "Invalid upstream molecule; the reference path does not drop benchmark rows"
            )
        DataStructs.ConvertToNumpyArray(
            generator.GetFingerprint(molecule), values[index]
        )
    return values


def validate(
    cache: Path,
    output: Path,
    datasets: list[str],
    seeds: list[int],
    *,
    download: bool,
    strategy: str,
):
    from tdc import Evaluator
    from tdc.benchmark_group import admet_group
    from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier

    if download:
        download_benchmarks(cache)
    group = admet_group(path=str(cache.resolve()))
    records = []
    for dataset in datasets:
        benchmark = load_benchmark(cache, dataset)
        task = benchmark.task
        evaluator = Evaluator(name=task.upstream_metric)
        test_features = (
            fingerprints(benchmark.test.Drug) if strategy == "random-forest" else None
        )
        for seed in seeds:
            train, valid = group.get_train_valid_split(
                seed=seed, benchmark=dataset, split_type="default"
            )
            if strategy == "mean":
                predictions = np.repeat(float(train.Y.mean()), len(benchmark.test))
            else:
                features = fingerprints(train.Drug)
                model_type = (
                    RandomForestRegressor
                    if task.task_type == "regression"
                    else RandomForestClassifier
                )
                model = model_type(
                    n_estimators=128,
                    min_samples_leaf=2,
                    max_features="sqrt",
                    random_state=seed,
                    n_jobs=1,
                )
                model.fit(features, train.Y.to_numpy())
                predictions = (
                    model.predict(test_features)
                    if task.task_type == "regression"
                    else model.predict_proba(test_features)[
                        :, list(model.classes_).index(1)
                    ]
                )
            run_output = output / dataset / f"seed-{seed}"
            prediction_file = run_output / "external_predictions.csv"
            canonical = partition_table(
                benchmark.test, task, "test", predictions=predictions
            )
            _write_csv(prediction_file, canonical[["sample_id", "prediction"]])
            summary = evaluate_tdc(
                cache, dataset, prediction_file, run_output / "evaluation"
            )
            expected = float(evaluator(benchmark.test.Y.to_numpy(), predictions))
            actual = float(summary["reported_metrics"][task.metric])
            if not np.isclose(actual, expected, rtol=0.0, atol=1e-12):
                raise AssertionError(
                    "PLB metric differs from the raw upstream evaluator"
                )
            group_result = group.evaluate({dataset: predictions}, save_dict=False)
            rounded = float(group_result[dataset][task.upstream_metric])
            if not np.isclose(round(actual, 3), rounded, rtol=0.0, atol=1e-12):
                raise AssertionError("PLB metric differs from upstream group rounding")
            receipt = run_output / "evaluation" / "evaluation_receipt.json"
            if not verify_receipt(receipt)["valid"]:
                raise AssertionError("Generated receipt failed verification")
            record = {
                "dataset": dataset,
                "seed": seed,
                "strategy": strategy,
                "n_train": len(train),
                "n_valid": len(valid),
                "n_test": len(benchmark.test),
                "metric": task.metric,
                "upstream_metric": task.upstream_metric,
                "plb_score": actual,
                "upstream_raw_score": expected,
                "upstream_group_score_3dp": rounded,
                "absolute_error": abs(actual - expected),
                "protocol": task.protocol,
                "train_val_sha256": task.train_val_sha256,
                "test_sha256": task.test_sha256,
                "receipt_hash_valid": True,
            }
            records.append(record)
            print(json.dumps(record), flush=True)
    versions = {}
    for name in ("PyTDC", "numpy", "pandas", "scikit-learn", "rdkit-pypi", "rdkit"):
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            pass
    result = {
        "schema_version": "tdc-parity-result/v1",
        "data_provenance": "real_public_upstream_benchmark",
        "source": SOURCE_URL,
        "archive_id": ARCHIVE_ID,
        "archive_sha256": ARCHIVE_SHA256,
        "versions": versions,
        "tolerance": 1e-12,
        "records": records,
        "limitations": [
            "These are reproducible baseline scores, not a leaderboard submission or a competitive-model claim.",
            "Variation across training/split seeds is distinct from test-population confidence intervals.",
            "Raw benchmark rows and model predictions are not included in this aggregate verification record.",
        ],
    }
    atomic_write_json(output / "verification.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path("outputs/tdc"))
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs/tdc-validation")
    )
    parser.add_argument("--dataset", action="append", choices=sorted(TASKS))
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    parser.add_argument(
        "--strategy", choices=["mean", "random-forest"], default="random-forest"
    )
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    validate(
        args.cache_dir,
        args.output_dir,
        args.dataset or list(TASKS),
        args.seeds,
        download=args.download,
        strategy=args.strategy,
    )


if __name__ == "__main__":
    main()
