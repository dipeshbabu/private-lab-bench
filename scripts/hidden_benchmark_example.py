"""Synthetic owner workflow; no real hidden data or independent researcher claim."""

from hashlib import sha256
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from privatelabbench.hidden_benchmarks import evaluate_benchmark, benchmark_template
from privatelabbench.leaderboards import build_leaderboard, render_leaderboard
from privatelabbench.privacy.export import atomic_write_json, publish_shareable_artifact
from privatelabbench.protocols import EvaluationProtocol, resolve_protocol
from privatelabbench.scoring import score_local


def run(output, mode="owner-only"):
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose an empty example output directory")
    output.mkdir(parents=True, exist_ok=True)
    generator = np.random.default_rng(13)
    x = generator.normal(size=48)
    features = pd.DataFrame(
        {"sample_id": [f"synthetic-{i:04d}" for i in range(len(x))], "measurement": x}
    )
    features.to_csv(output / "features.csv", index=False)
    labels = pd.DataFrame(
        {
            "sample_id": features.sample_id,
            "target": 1.5 * x + generator.normal(scale=0.15, size=len(x)),
        }
    )
    labels.to_csv(output / "owner-labels.csv", index=False)
    rules = resolve_protocol("plb://generic/regression@1.0.0").as_dict()
    rules["id"] = "plb://examples/hidden-regression"
    rules["ranking"] = {
        "metric": "mae",
        "rule": "conservative_interval_ties",
        "practical_tie_tolerance": 0.02,
        "require_uncertainty": True,
    }
    definition = EvaluationProtocol.from_dict(rules)
    protocol = output / "protocol.yaml"
    protocol.write_text(yaml.safe_dump(rules))
    models = [
        {"id": f"synthetic-linear-{letter}", "revision": "v1"} for letter in ("a", "b")
    ]
    benchmark = {
        "id": "synthetic-hidden-example",
        "version": "1.0.0",
        "suite": "owner-hidden-benchmark",
        "protocol": "prediction-table/v1",
    }
    policy = {
        "schema_version": "release-policy/v1",
        "id": "explicit-synthetic-approval",
        "enabled": True,
        "require_privacy_audit": False,
        "include_protocol": True,
        "include_submission": True,
        "include_source_receipts": True,
        "public_models": models,
        "public_submission_ids": ["sub-a", "sub-b"],
        "public_benchmark": benchmark,
    }
    spec = {
        "schema_version": "hidden-benchmark/v1",
        "id": benchmark["id"],
        "version": benchmark["version"],
        "protocol": str(protocol),
        "protocol_sha256": definition.sha256,
        "input_access": (
            "owner_only" if mode == "owner-only" else "approved_participant_inputs"
        ),
        "private_input": {
            "path": str(output / "owner-labels.csv"),
            "sample_id_column": "sample_id",
            "target_column": "target",
            "slice_columns": [],
        },
        "submission": {
            "sample_id_column": "sample_id",
            "prediction_column": "prediction",
        },
        "release": policy,
    }
    spec_path = output / "owner.yaml"
    spec_path.write_text(yaml.safe_dump(spec))
    if mode == "participant":
        benchmark_template(spec_path, output / "participant-template.csv")
    receipts = []
    for index, coefficient in enumerate((1.45, 0.2)):
        model_folder = output / f"model-{index}"
        model_folder.mkdir()
        artifact = model_folder / "weights.json"
        artifact.write_text(
            json.dumps(
                {
                    "schema_version": "linear-model/v1",
                    "feature_names": ["measurement"],
                    "coefficients": [coefficient],
                    "intercept": 0.0,
                },
                sort_keys=True,
            )
            + "\n"
        )
        digest = sha256(artifact.read_bytes()).hexdigest()
        manifest = {
            "schema_version": "model-manifest/v1",
            "trust": "approved_local",
            "model": {**models[index], "artifact_sha256": digest},
            "artifact": {
                "path": str(artifact),
                "sha256": digest,
                "format": "numeric-json/v1",
            },
            "adapter": {"id": "plb.linear-json", "version": "1.0.0"},
            "task_type": "regression",
            "features": [
                {"name": "measurement", "unit": "dimensionless", "dtype": "float64"}
            ],
            "sample_id_column": "sample_id",
            "preprocessing": {"version": "identity/v1", "missing_values": "reject"},
            "postprocessing": {"version": "identity/v1", "class_labels": []},
            "permissions": {
                "network": False,
                "filesystem": "declared_local_io",
                "execution": "trusted_in_process",
            },
            "deterministic": True,
            "provenance": "Invented synthetic example formula; not a fitted or validated scientific model.",
        }
        model_path = model_folder / "model.yaml"
        model_path.write_text(yaml.safe_dump(manifest))
        scored = score_local(
            model_path,
            output / "features.csv",
            model_folder / "predictions.csv",
            data_units={"measurement": "dimensionless"},
        )
        result_dir = output / f"submission-{index}"
        evaluate_benchmark(
            spec_path,
            scored["predictions"],
            result_dir,
            submission_id=f"sub-{chr(97+index)}",
            model=models[index],
            scoring_provenance=scored["provenance"] if mode == "owner-only" else None,
        )
        receipts.append(result_dir / "evaluation_receipt.shareable.json")
    table = build_leaderboard(receipts, str(protocol))
    atomic_write_json(output / "leaderboard.json", table)
    public = output / "leaderboard.shareable.json"
    decision = publish_shareable_artifact(table, policy, public)
    if decision.decision != "allow":
        raise ValueError("Synthetic example policy did not approve its result")
    approved = json.loads(public.read_text())
    (output / "leaderboard.md").write_text(render_leaderboard(approved))
    print(f"Synthetic aggregate leaderboard: {public}")
    print(
        "Owner labels, feature files, normalized evaluation tables, and provenance remain local."
    )
    return approved


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs/hidden-example")
    )
    parser.add_argument(
        "--mode", choices=["owner-only", "participant"], default="owner-only"
    )
    args = parser.parse_args()
    run(args.output_dir, args.mode)
