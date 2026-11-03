"""Opt-in real Matbench five-fold parity against the pinned upstream package."""

import argparse
import json
import os
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from privatelabbench.core.local_io import atomic_write_csv
from privatelabbench.integrations.matbench import (
    FOLDS_SHA256,
    REFERENCE_COMMIT,
    REFERENCE_SCORER_SHA256,
    TASKS,
    download_benchmark,
    evaluate_matbench,
    load_snapshot,
)
from privatelabbench.privacy.export import atomic_write_json
from privatelabbench.reports.receipt import verify_receipt


def validate(cache, output, datasets, strategies, download=False):
    import inspect
    from hashlib import sha256

    from matbench.bench import MatbenchBenchmark
    from matbench.data_ops import score_array

    if (
        sha256(Path(inspect.getsourcefile(score_array)).read_bytes()).hexdigest()
        != REFERENCE_SCORER_SHA256
    ):
        raise ValueError(
            "Install the pinned corrected upstream reference package, not legacy PyPI 0.6 scoring"
        )
    cache = Path(cache).resolve()
    output = Path(output).resolve()
    os.environ["MATMINER_DATA"] = str(cache)
    results = []
    for dataset in datasets:
        if download:
            download_benchmark(cache, dataset)
        snapshot = load_snapshot(cache, dataset)
        task = snapshot.task
        for strategy in strategies:
            group = MatbenchBenchmark(subset=[dataset], autoload=True)
            reference = next(iter(group.tasks))
            tables = []
            upstream = []
            for fold in snapshot.folds:
                number = fold["fold"]
                train = reference.get_train_and_val_data(number, as_type="df")
                test = reference.get_test_data(
                    number, include_target=True, as_type="df"
                )
                if list(train.index) != list(fold["train"]) or list(test.index) != list(
                    fold["test"]
                ):
                    raise AssertionError("Official fold/sample order differs")
                y_train = train[task.target].to_numpy(dtype=float)
                y_test = test[task.target].to_numpy(dtype=float)
                if not np.array_equal(
                    y_test,
                    snapshot.labels.loc[list(fold["test"])].target.to_numpy(
                        dtype=float
                    ),
                ):
                    raise AssertionError(
                        "Native cached targets differ from official loader"
                    )
                generator = np.random.default_rng(13 + number)
                if strategy == "mean":
                    predictions = np.repeat(float(y_train.mean()), len(test))
                elif task.task_type == "classification":
                    predictions = generator.uniform(0.05, 0.45, len(test))
                else:
                    predictions = y_train.mean() + y_train.std() * generator.normal(
                        size=len(test)
                    )
                reference.record(
                    number,
                    predictions,
                    params={"strategy": strategy, "seed": 13 + number},
                )
                expected = float(
                    score_array(y_test, predictions, task.task_type)[
                        task.upstream_metric
                    ]
                )
                tables.append(
                    pd.DataFrame(
                        {
                            "fold": number,
                            "sample_id": test.index,
                            "prediction": predictions,
                        }
                    )
                )
                upstream.append(expected)
            folder = output / dataset / strategy
            table = folder / "external-predictions.csv"
            atomic_write_csv(table, pd.concat(tables, ignore_index=True))
            result = evaluate_matbench(cache, dataset, table, folder / "evaluation")
            shared = result["artifact"]["shareable"]
            official_stats = {
                key: float(value)
                for key, value in reference.scores[task.upstream_metric].items()
            }
            for record, expected in zip(shared["folds"], upstream):
                if not np.isclose(record["score"], expected, rtol=0, atol=1e-12):
                    raise AssertionError(
                        "Fold score differs from actual upstream evaluator"
                    )
                receipt = (
                    folder
                    / "evaluation"
                    / f"fold-{record['fold']}"
                    / "evaluation_receipt.json"
                )
                if not verify_receipt(receipt)["valid"]:
                    raise AssertionError("Generated fold receipt failed verification")
            for statistic, value in official_stats.items():
                if not np.isclose(
                    shared["fold_score_statistics"][statistic],
                    value,
                    rtol=0,
                    atol=1e-12,
                ):
                    raise AssertionError(
                        "Task fold aggregation differs from actual upstream scores"
                    )
            record = {
                "dataset": dataset,
                "strategy": strategy,
                "target_unit": task.unit,
                "metric": task.metric,
                "upstream_metric": task.upstream_metric,
                "folds": [
                    {
                        **row,
                        "upstream_score": expected,
                        "absolute_error": abs(row["score"] - expected),
                    }
                    for row, expected in zip(shared["folds"], upstream)
                ],
                "plb_statistics": shared["fold_score_statistics"],
                "upstream_statistics": official_stats,
                "protocol": task.protocol,
                "data_sha256": task.data_sha256,
                "fold_receipts_verified": True,
            }
            results.append(record)
            print(
                json.dumps(
                    {
                        "dataset": dataset,
                        "strategy": strategy,
                        "mean": shared["fold_score_statistics"]["mean"],
                        "max_error": max(
                            item["absolute_error"] for item in record["folds"]
                        ),
                    }
                ),
                flush=True,
            )
    result = {
        "schema_version": "matbench-parity-result/v1",
        "data_provenance": "real_public_upstream_benchmark",
        "reference_commit": REFERENCE_COMMIT,
        "reference_scorer_sha256": REFERENCE_SCORER_SHA256,
        "fold_definition_sha256": FOLDS_SHA256,
        "versions": {
            name: version(name)
            for name in (
                "matbench",
                "matminer",
                "numpy",
                "pandas",
                "scikit-learn",
                "pymatgen",
                "monty",
            )
        },
        "tolerance": 1e-12,
        "records": results,
        "limitations": [
            "These mean/fixed-random baseline scores test interoperability, not competitive models or a leaderboard submission.",
            "Classification uses corrected upstream probability ROC-AUC; historical thresholded Matbench leaderboard scores are not interchangeable.",
            "Fold standard deviation describes the five scores; it is not a population confidence interval.",
            "Only aggregate results are stored in this verification record; raw benchmark rows and predictions remain local.",
        ],
    }
    atomic_write_json(output / "verification.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path("outputs/matbench"))
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs/matbench-validation")
    )
    parser.add_argument("--dataset", action="append", choices=sorted(TASKS))
    parser.add_argument("--strategy", action="append", choices=["mean", "fixed-random"])
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    validate(
        args.cache_dir,
        args.output_dir,
        args.dataset or list(TASKS),
        args.strategy or ["mean", "fixed-random"],
        args.download,
    )
