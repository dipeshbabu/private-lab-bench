"""Opt-in real DMS parity; no protein model weights or remote model code are loaded."""

import argparse
from hashlib import sha256
from importlib.metadata import version
import importlib.util
import json, sys
from pathlib import Path
import re

import numpy as np
import pandas as pd
from Bio.Align import substitution_matrices

from privatelabbench.core.local_io import atomic_write_csv
from privatelabbench.core.public_data import download_verified
from privatelabbench.integrations.proteingym import (
    ASSAYS,
    REFERENCE_COMMIT,
    REFERENCE_SHA256,
    ARCHIVE_SHA256,
    REFERENCE_FILE,
    download_assays,
    load_assay,
    evaluate_proteingym,
)
from privatelabbench.privacy.export import atomic_write_json
from privatelabbench.reports.receipt import verify_receipt

SCORER_SHA256 = "0002bc1b031c02dc2d67fde53da092c8fd301415645e8e83b425b4183570eba2"
CONSTANTS_SHA256 = "e7b53a99952067b8c378d9072d38d71572b624fa357251bb8d3f53bf9b073e7a"


def blosum_scores(mutants):
    matrix = substitution_matrices.load("BLOSUM62")
    values = []
    for mutant in mutants:
        total = 0.0
        for change in str(mutant).split(":"):
            match = re.fullmatch(r"([A-Z*])([1-9][0-9]*)([A-Z*])", change)
            if not match:
                raise ValueError(
                    "Unsupported mutation descriptor; the reference baseline does not drop variants"
                )
            wild, _, altered = match.groups()
            total += float(matrix[wild, altered] - matrix[wild, wild])
        values.append(total)
    return np.asarray(values, dtype=float)


def reference_module(folder):
    folder = Path(folder)
    base = f"https://raw.githubusercontent.com/OATML-Markslab/ProteinGym/{REFERENCE_COMMIT}/proteingym/"
    path = folder / "performance_DMS_benchmarks.py"
    download_verified(path, base + path.name, SCORER_SHA256)
    download_verified(
        folder / "constants.json", base + "constants.json", CONSTANTS_SHA256
    )
    specification = importlib.util.spec_from_file_location(
        "proteingym_pinned_reference", path
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def validate(cache, output, names, *, download=False, run_upstream_pipeline=False):
    cache = Path(cache).resolve()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if download:
        download_assays(cache, names)
    reference = reference_module(output / "reference-source")
    tables = []
    expected = {"blosum62": {}, "fixed_random": {}}
    reference_scores = output / "reference-scores"
    reference_scores.mkdir(exist_ok=True)
    for index, name in enumerate(sorted(names)):
        snapshot = load_assay(cache, name)
        raw = pd.read_csv(cache / snapshot.assay.filename)
        scores = {
            "blosum62": blosum_scores(snapshot.frame.mutant),
            "fixed_random": np.random.default_rng(13 + index).normal(
                size=len(snapshot.frame)
            ),
        }
        table = pd.DataFrame(
            {
                "assay": name,
                "mutant": snapshot.frame.mutant,
                "DMS_score": snapshot.frame.target,
                "DMS_score_bin": raw.DMS_score_bin,
            }
        )
        for model, values in scores.items():
            table[model] = values
            expected[model][name] = float(
                reference.spearmanr(snapshot.frame.target.to_numpy(), values)[0]
            )
        atomic_write_csv(reference_scores / (name + ".csv"), table)
        tables.append(table)
    combined = output / "model-scores.csv"
    atomic_write_csv(combined, pd.concat(tables, ignore_index=True))
    results = []
    for model in expected:
        identity = {
            "id": model.replace("_", "-"),
            "revision": (
                "biopython-" + version("biopython")
                if model == "blosum62"
                else "seed-13"
            ),
        }
        result = evaluate_proteingym(
            cache,
            names,
            combined,
            output / model,
            model=identity,
            score_direction="higher",
            prediction_column=model,
        )
        shared = result["artifact"]["shareable"]
        differences = []
        for row in shared["per_assay"]:
            error = abs(row["spearman"] - expected[model][row["assay"]])
            differences.append(error)
            if error > 1e-12:
                raise AssertionError(
                    "Assay Spearman differs from the pinned upstream evaluator"
                )
            path = output / model / row["assay"] / "evaluation_receipt.json"
            if not verify_receipt(path)["valid"]:
                raise AssertionError("Assay receipt failed verification")
        results.append(
            {
                "model": identity,
                "per_assay": [
                    {
                        **row,
                        "upstream_spearman": expected[model][row["assay"]],
                        "absolute_error": abs(
                            row["spearman"] - expected[model][row["assay"]]
                        ),
                    }
                    for row in shared["per_assay"]
                ],
                "hierarchical_mean": shared["metrics"]["spearman"],
                "per_function": shared["per_function"],
                "assay_receipts_verified": True,
                "max_error": max(differences),
            }
        )
        print(
            json.dumps(
                {
                    "model": model,
                    "mean": shared["metrics"]["spearman"],
                    "max_error": max(differences),
                }
            ),
            flush=True,
        )
    pipeline_checked = False
    if run_upstream_pipeline:
        metadata = pd.read_csv(cache / REFERENCE_FILE)
        metadata = metadata[metadata.DMS_id.isin(names)]
        subset = output / "reference-subset.csv"
        metadata.to_csv(subset, index=False)
        config = output / "reference-config.json"
        config.write_text(
            json.dumps(
                {
                    "model_list_zero_shot_substitutions_DMS": {
                        name: {"model_type": "Reproducibility control"}
                        for name in expected
                    }
                }
            )
        )
        arguments = sys.argv
        try:
            sys.argv = [
                "performance_DMS_benchmarks.py",
                "--input_scoring_files_folder",
                str(reference_scores),
                "--output_performance_file_folder",
                str(output / "upstream-performance"),
                "--DMS_reference_file_path",
                str(subset),
                "--DMS_data_folder",
                str(cache),
                "--config_file",
                str(config),
            ]
            np.random.seed(13)
            reference.main()
        finally:
            sys.argv = arguments
        summary = pd.read_csv(
            output
            / "upstream-performance/Spearman/Summary_performance_DMS_substitutions_Spearman.csv"
        ).set_index("Model_name")
        for record, key in zip(results, expected):
            official = float(summary.loc[key, "Average_Spearman"])
            if abs(float(np.round(record["hierarchical_mean"], 3)) - official) > 1e-12:
                raise AssertionError(
                    "Hierarchical aggregation differs from the actual upstream pipeline rounding"
                )
            record["actual_upstream_hierarchical_mean_3dp"] = official
        pipeline_checked = True
    record = {
        "schema_version": "proteingym-parity-result/v1",
        "data_provenance": "real_public_upstream_benchmark",
        "benchmark_scope": "selected_assay_subset",
        "reference_commit": REFERENCE_COMMIT,
        "reference_scorer_sha256": SCORER_SHA256,
        "reference_file_sha256": REFERENCE_SHA256,
        "archive_sha256": ARCHIVE_SHA256,
        "assay_count": len(names),
        "full_benchmark_assay_count": 217,
        "actual_upstream_pipeline_checked": pipeline_checked,
        "versions": {
            name: version(name)
            for name in ("biopython", "numpy", "pandas", "scipy", "scikit-learn")
        },
        "tolerance": 1e-12,
        "models": results,
        "limitations": [
            "BLOSUM62 substitution sums and fixed-random scores are reproducibility controls, not competitive protein AI model claims.",
            "The selected subset is not the full ProteinGym leaderboard; no aggregate uncertainty or clinical validation is claimed.",
            "Only aggregate statistics are retained here; sequences, mutation rows, and raw model scores remain local.",
        ],
    }
    atomic_write_json(output / "verification.json", record)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path("outputs/proteingym"))
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs/proteingym-validation")
    )
    parser.add_argument("--assay", action="append", choices=sorted(ASSAYS))
    parser.add_argument("--download", action="store_true")
    parser.add_argument(
        "--run-upstream-pipeline",
        action="store_true",
        help="Also execute upstream's full summary/10,000-resample SE pipeline; only point summaries are compared.",
    )
    args = parser.parse_args()
    validate(
        args.cache_dir,
        args.output_dir,
        args.assay or list(ASSAYS),
        download=args.download,
        run_upstream_pipeline=args.run_upstream_pipeline,
    )
