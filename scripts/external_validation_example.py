"""Local declared-validation walkthrough: synthetic inputs or a pinned public TDC cache."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from privatelabbench.runner import run_config


def run(output: Path, tdc_cache: Path | None = None):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Choose an empty output directory to preserve existing work")
    if tdc_cache:
        from privatelabbench.integrations.tdc import load_benchmark, partition_table

        benchmark = load_benchmark(tdc_cache, "caco2_wang")
        model = {
            "schema_version": "constant-reference-model/v1",
            "prediction": float(benchmark.train_val.Y.mean()),
            "training_source_sha256": benchmark.task.train_val_sha256,
        }
        frame = partition_table(
            benchmark.test,
            benchmark.task,
            "test",
            predictions=np.repeat(model["prediction"], len(benchmark.test)),
        )
        protocol = benchmark.task.protocol
        benchmark_identity = benchmark.identity()
        visibility, overlap, relationship = "public", "not_assessed", "model_developer"
        model_id = "tdc-constant-reference"
        provenance = "Pinned public TDC Caco2 fixed test records; no independent-validation claim."
    else:
        generator = np.random.default_rng(13)
        x = generator.normal(size=80)
        model = {
            "schema_version": "linear-reference-model/v1",
            "coefficient": 0.8,
            "intercept": 0.2,
        }
        frame = pd.DataFrame(
            {
                "sample_id": [f"synthetic-{i}" for i in range(80)],
                "target": x + generator.normal(scale=0.2, size=80),
                "prediction": model["coefficient"] * x + model["intercept"],
                "baseline": np.zeros(80),
                "site": ["a"] * 40 + ["b"] * 40,
            }
        )
        protocol = "plb://generic/regression@1.0.0"
        benchmark_identity = None
        visibility, overlap, relationship = "private", "not_assessed", "undisclosed"
        model_id = "synthetic-linear-reference"
        provenance = "Synthetic private-like observations; not real private data or an independent researcher trial."
    artifact = output / "model.json"
    artifact.write_text(json.dumps(model, sort_keys=True) + "\n", encoding="utf-8")
    digest = sha256(artifact.read_bytes()).hexdigest()
    model_identity = {
        "id": model_id,
        "revision": digest[:16],
        "artifact_sha256": digest,
    }
    predictions = output / "predictions.csv"
    frame.to_csv(predictions, index=False)
    context = {
        "schema_version": "external-validation-profile/v1",
        "model": model_identity,
        "dataset": {
            "visibility": visibility,
            "training_overlap": overlap,
            "provenance_statement": provenance,
        },
        "evaluator_relationship": relationship,
    }
    policy = {
        "schema_version": "release-policy/v1",
        "id": "example-explicit-approval",
        "enabled": True,
        "require_privacy_audit": False,
        "include_protocol": True,
        "public_validation": {
            key: context[key] for key in ("model", "dataset", "evaluator_relationship")
        },
    }
    settings = {
        "project": model_id,
        "protocol": protocol,
        "input": {
            "path": str(predictions),
            "sample_id_column": "sample_id",
            "target_column": "target",
            "prediction_column": "prediction",
        },
        "external_validation": context,
        "release": policy,
        "report": {
            "json": str(output / "run.json"),
            "markdown": str(output / "run.md"),
            "manifest": str(output / "run_manifest.json"),
        },
        "audit": {"path": str(output / "audit.jsonl")},
    }
    if benchmark_identity:
        settings["benchmark"] = benchmark_identity
        settings["release"]["public_benchmark"] = benchmark_identity
    else:
        settings["input"].update(
            {"baseline_prediction_column": "baseline", "slice_columns": ["site"]}
        )
    config = output / "evaluation.yaml"
    config.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
    result = run_config(str(config))
    print(f"Local evaluation: {result['json_report']}")
    print(f"Approved aggregate receipt: {output / 'run_receipt.shareable.json'}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs/external-validation-example")
    )
    parser.add_argument(
        "--tdc-cache",
        type=Path,
        help="Use an already fetched, verified public Caco2 cache; performs no download.",
    )
    args = parser.parse_args()
    run(args.output_dir, args.tdc_cache)
