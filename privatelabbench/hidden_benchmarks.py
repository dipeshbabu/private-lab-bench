"""Benchmark-owner prediction evaluation; no submitted code is executed."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from privatelabbench.aggregate import model_identity
from privatelabbench.core.local_io import atomic_write_csv
from privatelabbench.privacy.export import (
    _mapping,
    _token,
    atomic_write_json,
    validate_policy,
)
from privatelabbench.protocols import (
    EvaluationProtocol,
    VERSION_PATTERN,
    resolve_protocol,
)

SPEC_SCHEMA = "hidden-benchmark/v1"
SUBMISSION_SCHEMA = "benchmark-submission/v1"
DIGEST = re.compile(r"[a-f0-9]{64}\Z")


def _fields(value, required, optional=()):
    if (
        not isinstance(value, Mapping)
        or not set(required) <= set(value)
        or set(value) - set(required) - set(optional)
    ):
        raise ValueError("Unsupported or incomplete benchmark/submission fields")
    return dict(value)


def _column(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError("Declare nonempty benchmark column names")
    return value


def _path(value, base):
    if not isinstance(value, str) or "://" in value or value.startswith(("\\\\", "//")):
        raise ValueError("Benchmark inputs must be explicitly named local files")
    path = Path(value)
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


@dataclass(frozen=True)
class HiddenBenchmark:
    canonical: bytes
    base: Path
    protocol: EvaluationProtocol
    source_sha256: str
    source: Path

    def as_dict(self):
        return json.loads(self.canonical)

    @property
    def input_path(self):
        return _path(self.as_dict()["private_input"]["path"], self.base)

    def identity(self):
        value = self.as_dict()
        return {
            "id": value["id"],
            "version": value["version"],
            "suite": "owner-hidden-benchmark",
            "protocol": "prediction-table/v1",
        }


def load_benchmark_spec(path, *, content=None):
    source = Path(path).resolve()
    content = source.read_bytes() if content is None else content
    value = _fields(
        yaml.safe_load(content),
        {
            "schema_version",
            "id",
            "version",
            "protocol",
            "protocol_sha256",
            "private_input",
            "submission",
            "input_access",
        },
        {"release"},
    )
    if value["schema_version"] != SPEC_SCHEMA or value["input_access"] not in {
        "approved_participant_inputs",
        "owner_only",
    }:
        raise ValueError("Unsupported hidden benchmark or input-access mode")
    _token(value["id"])
    if not isinstance(value["version"], str) or not re.fullmatch(
        VERSION_PATTERN, value["version"]
    ):
        raise ValueError("Benchmark versions require semantic versioning")
    if not isinstance(value["protocol"], str):
        raise ValueError("An exact versioned protocol is required")
    protocol = resolve_protocol(value["protocol"], base=source.parent)
    if value["protocol_sha256"] != protocol.sha256:
        raise ValueError("Hidden benchmark protocol digest changed")
    if not protocol.as_dict()["input_schema"]["require_sample_id"]:
        raise ValueError("Hidden benchmark protocols must require stable sample IDs")
    private = _fields(
        value["private_input"],
        {"path", "sample_id_column", "target_column", "slice_columns"},
    )
    _path(private["path"], source.parent)
    names = [_column(private[key]) for key in ("sample_id_column", "target_column")]
    if not isinstance(private["slice_columns"], list):
        raise ValueError("Declare slice columns explicitly")
    names += [_column(name) for name in private["slice_columns"]]
    if len(set(names)) != len(names) or any(
        name in {"sample_id", "target", "prediction"}
        for name in private["slice_columns"]
    ):
        raise ValueError(
            "Benchmark identifier, target, and slice columns must be separate"
        )
    submission = _fields(
        value["submission"],
        {"sample_id_column"},
        {"prediction_column", "prediction_columns"},
    )
    _column(submission["sample_id_column"])
    multi = protocol.as_dict()["task_type"] == "multiclass"
    if multi:
        if (
            "prediction_column" in submission
            or not isinstance(submission.get("prediction_columns"), list)
            or len(submission["prediction_columns"])
            != len(protocol.as_dict()["input_schema"]["class_labels"])
        ):
            raise ValueError(
                "Multiclass submissions require one declared probability column per ordered class"
            )
        prediction_columns = [
            _column(name) for name in submission["prediction_columns"]
        ]
    else:
        if "prediction_columns" in submission or "prediction_column" not in submission:
            raise ValueError(
                "Scalar submissions require one explicit prediction column"
            )
        prediction_columns = [_column(submission["prediction_column"])]
    if (
        len(set([submission["sample_id_column"], *prediction_columns]))
        != len(prediction_columns) + 1
        or "target" in prediction_columns
    ):
        raise ValueError(
            "Submission prediction/ID columns must be unique and exclude targets"
        )
    canonical_predictions = (
        ["prediction"]
        if not multi
        else [f"probability_{index}" for index in range(len(prediction_columns))]
    )
    if set(canonical_predictions) & set(private["slice_columns"]):
        raise ValueError(
            "Owner slice columns must be separate from normalized predictions"
        )
    if "release" in value:
        validate_policy(value["release"])
    return HiddenBenchmark(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode(),
        source.parent,
        protocol,
        sha256(content).hexdigest(),
        source,
    )


def _owner_table(benchmark):
    rules = benchmark.as_dict()["private_input"]
    content = benchmark.input_path.read_bytes()
    dtype = {rules["sample_id_column"]: "string"}
    if benchmark.protocol.as_dict()["task_type"] != "regression":
        dtype[rules["target_column"]] = "string"
    frame = pd.read_csv(BytesIO(content), dtype=dtype)
    needed = [
        rules["sample_id_column"],
        rules["target_column"],
        *rules["slice_columns"],
    ]
    if not set(needed) <= set(frame) or frame.empty or frame[needed].isna().any().any():
        raise ValueError("Owner evaluation table is incomplete")
    ids = frame[rules["sample_id_column"]]
    if ids.str.strip().eq("").any() or ids.duplicated().any():
        raise ValueError("Owner sample IDs must be complete and unique")
    return frame[needed].copy(), sha256(content).hexdigest()


def submission_identity(value):
    value = _fields(
        value,
        {
            "schema_version",
            "id",
            "model",
            "artifact_sha256",
            "input_access",
            "submission_kind",
        },
    )
    if (
        value["schema_version"] != SUBMISSION_SCHEMA
        or value["input_access"] not in {"approved_participant_inputs", "owner_only"}
        or value["submission_kind"]
        not in {"participant_predictions", "owner_scored_predictions"}
    ):
        raise ValueError("Invalid benchmark submission identity")
    _token(value["id"])
    value["model"] = model_identity(value["model"])
    if not isinstance(value["artifact_sha256"], str) or not DIGEST.fullmatch(
        value["artifact_sha256"]
    ):
        raise ValueError(
            "Submission identity needs its exact prediction artifact digest"
        )
    if (
        value["input_access"] == "owner_only"
        and value["submission_kind"] != "owner_scored_predictions"
    ):
        raise ValueError("Hidden inputs require owner-side trusted scoring")
    return value


def sanitize_submission(value, policy):
    source = submission_identity(value)
    if source["id"] not in policy.get("public_submission_ids", []) or source[
        "model"
    ] not in [model_identity(item) for item in policy.get("public_models", [])]:
        raise ValueError("Submission/model identity needs explicit owner approval")
    return source


def prepare_submission(
    benchmark, predictions, *, submission_id, model, scoring_provenance=None
):
    value = benchmark.as_dict()
    owner, owner_digest = _owner_table(benchmark)
    content = Path(predictions).read_bytes()
    columns = value["submission"]
    sample = columns["sample_id_column"]
    frame = pd.read_csv(BytesIO(content), dtype={sample: "string"})
    probability_columns = columns.get("prediction_columns") or [
        columns["prediction_column"]
    ]
    if set(frame) != {sample, *probability_columns}:
        raise ValueError(
            "Submissions may contain only declared IDs and predictions; target/feature columns are rejected"
        )
    ids = frame[sample]
    expected = owner[value["private_input"]["sample_id_column"]]
    if (
        ids.isna().any()
        or ids.str.strip().eq("").any()
        or ids.duplicated().any()
        or set(ids) != set(expected)
    ):
        raise ValueError(
            "Submission IDs must exactly cover the owner evaluation records"
        )
    aligned = frame.set_index(sample).loc[expected].reset_index()
    scores = (
        aligned[probability_columns]
        .apply(pd.to_numeric, errors="raise")
        .to_numpy(dtype=float)
    )
    if not np.isfinite(scores).all():
        raise ValueError("Submission predictions must be finite")
    task = benchmark.protocol.as_dict()["task_type"]
    if task != "regression" and (
        np.any(scores < 0)
        or np.any(scores > 1)
        or task == "multiclass"
        and not np.allclose(scores.sum(axis=1), 1, rtol=1e-5, atol=1e-8)
    ):
        raise ValueError(
            "Classification submissions require valid probabilities in declared class order"
        )
    kind = "participant_predictions"
    if scoring_provenance is not None:
        provenance = _mapping(
            json.loads(Path(scoring_provenance).read_text(encoding="utf-8"))
        )
        from privatelabbench.external_validation import model_metadata
        from privatelabbench.scoring import ADAPTER_ID, ADAPTER_VERSION

        model_metadata(provenance.get("model"))
        if (
            provenance.get("adapter") != {"id": ADAPTER_ID, "version": ADAPTER_VERSION}
            or _mapping(provenance.get("permissions", {})).get("network") is not False
            or provenance.get("deterministic") is not True
        ):
            raise ValueError(
                "Owner-side provenance requires the explicitly approved deterministic local scorer"
            )
        if (
            provenance.get("schema_version") != "local-scoring-provenance/v1"
            or provenance.get("scope") != "local"
            or provenance.get("prediction_sha256") != sha256(content).hexdigest()
            or provenance.get("isolation") != "none_trusted_in_process"
            or provenance.get("task_type") != task
            or provenance.get("class_labels")
            != benchmark.protocol.as_dict()["input_schema"]["class_labels"]
            or {key: provenance.get("model", {}).get(key) for key in ("id", "revision")}
            != model_identity(model)
        ):
            raise ValueError(
                "Owner-scoring provenance does not match the submission/model"
            )
        kind = "owner_scored_predictions"
    if value["input_access"] == "owner_only" and kind != "owner_scored_predictions":
        raise ValueError(
            "Owner-only inputs cannot use ordinary participant prediction submissions"
        )
    identity = submission_identity(
        {
            "schema_version": SUBMISSION_SCHEMA,
            "id": submission_id,
            "model": model_identity(model),
            "artifact_sha256": sha256(content).hexdigest(),
            "input_access": value["input_access"],
            "submission_kind": kind,
        }
    )
    private = value["private_input"]
    targets = owner[private["target_column"]].to_numpy()
    if task == "regression":
        targets = pd.to_numeric(pd.Series(targets), errors="raise").to_numpy(
            dtype=float
        )
        if not np.isfinite(targets).all():
            raise ValueError("Owner regression targets must be finite")
    elif set(benchmark.protocol.as_dict()["input_schema"]["class_labels"]) == {
        "0",
        "1",
    }:
        numeric = pd.to_numeric(pd.Series(targets), errors="raise").to_numpy(
            dtype=float
        )
        if not np.isfinite(numeric).all() or not set(np.unique(numeric)) <= {0.0, 1.0}:
            raise ValueError("Owner binary targets must match declared numeric labels")
        targets = numeric.astype(int)
    result = pd.DataFrame(
        {
            "sample_id": expected.to_numpy(),
            "target": targets,
        }
    )
    canonical_predictions = (
        ["prediction"]
        if len(probability_columns) == 1
        else [f"probability_{index}" for index in range(len(probability_columns))]
    )
    for index, name in enumerate(canonical_predictions):
        result[name] = scores[:, index]
    for name in private["slice_columns"]:
        result[name] = owner[name].to_numpy()
    return (
        result,
        identity,
        {
            "owner_input_sha256": owner_digest,
            "benchmark_spec_sha256": benchmark.source_sha256,
            "submission_columns": probability_columns,
            "canonical_prediction_columns": canonical_predictions,
        },
    )


def evaluate_benchmark(
    spec,
    predictions,
    output_dir,
    *,
    submission_id,
    model,
    submission_manifest=None,
    scoring_provenance=None,
):
    from privatelabbench.runner import run_config

    output = Path(output_dir).resolve()
    source = Path(spec).resolve()
    sources = {
        source,
        Path(predictions).resolve(),
        *[
            Path(path).resolve()
            for path in (submission_manifest, scoring_provenance)
            if path
        ],
    }
    content = None
    deferred_error = None
    try:
        content = source.read_bytes()
        raw = yaml.safe_load(content)
        if isinstance(raw, dict):
            if isinstance(raw.get("private_input"), dict) and isinstance(
                raw["private_input"].get("path"), str
            ):
                sources.add(_path(raw["private_input"]["path"], source.parent))
            if isinstance(raw.get("protocol"), str) and not raw["protocol"].startswith(
                "plb://"
            ):
                sources.add(_path(raw["protocol"], source.parent))
    except (ValueError, OSError, yaml.YAMLError) as exc:
        deferred_error = exc
    names = (
        "owner_evaluation.csv",
        "evaluation.yaml",
        "evaluation.json",
        "evaluation.md",
        "evaluation_manifest.json",
        "evaluation_receipt.json",
        "evaluation_receipt.shareable.json",
        "evaluation_receipt.md",
        "audit.jsonl",
        "benchmark_input.json",
        "evaluation_receipt.shareable.release-audit.json",
        ".plb-release-ledger.json",
        ".plb-release.lock",
    )
    if {output / name for name in names} & sources:
        raise ValueError(
            "Benchmark output paths must preserve every owner/submission input"
        )
    public, markdown = (
        output / "evaluation_receipt.shareable.json",
        output / "evaluation_receipt.md",
    )
    public.unlink(missing_ok=True)
    markdown.unlink(missing_ok=True)
    if deferred_error is not None:
        raise deferred_error
    benchmark = load_benchmark_spec(spec, content=content)
    value = benchmark.as_dict()
    if isinstance(model, str):
        if "@" not in model:
            raise ValueError("Model identity requires id@revision")
        name, revision = model.rsplit("@", 1)
        model = {"id": name, "revision": revision}
    model = model_identity(model)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose an empty owner output directory")
    manifest = None
    if submission_manifest:
        manifest = _fields(
            yaml.safe_load(Path(submission_manifest).read_text(encoding="utf-8")),
            {"schema_version", "id", "model"},
            {"prediction_sha256", "citation", "participant"},
        )
        if (
            manifest["schema_version"] != "submission-manifest/v1"
            or manifest["id"] != submission_id
            or model_identity(manifest["model"]) != model_identity(model)
        ):
            raise ValueError(
                "Submission manifest identity conflicts with the explicit submission"
            )
        for field in ("citation", "participant"):
            if field in manifest and (
                not isinstance(manifest[field], str) or len(manifest[field]) > 1200
            ):
                raise ValueError(
                    "Participant/citation metadata must be bounded local text"
                )
    frame, identity, provenance = prepare_submission(
        benchmark,
        predictions,
        submission_id=submission_id,
        model=model,
        scoring_provenance=scoring_provenance,
    )
    if (
        manifest
        and manifest.get("prediction_sha256", identity["artifact_sha256"])
        != identity["artifact_sha256"]
    ):
        raise ValueError("Submission prediction artifact changed from its manifest")
    table = output / "owner_evaluation.csv"
    atomic_write_csv(table, frame)
    provenance.update(
        {"scope": "local", "submission_manifest": manifest, "submission": identity}
    )
    atomic_write_json(output / "benchmark_input.json", provenance)
    columns = provenance["canonical_prediction_columns"]
    settings = {
        "project": value["id"],
        "protocol": (
            benchmark.protocol.ref
            if value["protocol"].startswith("plb://")
            else str(_path(value["protocol"], benchmark.base))
        ),
        "protocol_sha256": benchmark.protocol.sha256,
        "benchmark": benchmark.identity(),
        "benchmark_submission": identity,
        "input": {
            "path": str(table),
            "sample_id_column": "sample_id",
            "target_column": "target",
            "slice_columns": value["private_input"]["slice_columns"],
            **(
                {"prediction_column": columns[0]}
                if len(columns) == 1
                else {"prediction_columns": columns}
            ),
        },
        "report": {
            "json": str(output / "evaluation.json"),
            "markdown": str(output / "evaluation.md"),
            "manifest": str(output / "evaluation_manifest.json"),
        },
        "audit": {"path": str(output / "audit.jsonl")},
        "release": value.get("release", benchmark.protocol.as_dict()["release"]),
        "hidden_benchmark_local": provenance,
    }
    config = output / "evaluation.yaml"
    config.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
    return run_config(str(config))


def benchmark_template(spec, output):
    benchmark = load_benchmark_spec(spec)
    value = benchmark.as_dict()
    if value["input_access"] != "approved_participant_inputs":
        raise ValueError(
            "Owner-only benchmark records cannot generate a participant template"
        )
    target = Path(output).resolve()
    if target.exists() or target in {benchmark.source, benchmark.input_path}:
        raise ValueError("Choose a fresh template path separate from all owner inputs")
    owner, _ = _owner_table(benchmark)
    frame = pd.DataFrame(
        {
            value["submission"]["sample_id_column"]: owner[
                value["private_input"]["sample_id_column"]
            ].to_numpy()
        }
    )
    for name in value["submission"].get("prediction_columns") or [
        value["submission"]["prediction_column"]
    ]:
        frame[name] = np.nan
    atomic_write_csv(target, frame)
    return {"n_samples": len(frame), "template": str(target)}


def benchmark_command(args):
    try:
        if args.command == "benchmark-template":
            result = benchmark_template(args.spec, args.out)
            print(
                f"Participant template: {result['template']} ({result['n_samples']} records)"
            )
            return 0
        result = evaluate_benchmark(
            args.spec,
            args.predictions,
            args.output_dir,
            submission_id=args.submission_id,
            model=args.model,
            submission_manifest=args.submission_manifest,
            scoring_provenance=args.scoring_provenance,
        )
        output = Path(args.output_dir).resolve()
        print(f"Local owner receipt: {output/'evaluation_receipt.json'}")
        public = output / "evaluation_receipt.shareable.json"
        print(
            f"Approved aggregate receipt: {public}"
            if public.exists()
            else "Public release requires owner approval; inspect the local release audit."
        )
        return (
            1
            if result.get("quality_gate", {}).get("status") == "fail"
            else (
                2
                if result.get("quality_gate", {}).get("status") == "investigate"
                else 0
            )
        )
    except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError):
        # Data parser/evaluator errors can contain targets or private IDs; keep them out of CLI responses.
        print(
            "Benchmark rejected. Check the owner configuration, submission schema/coverage, protocol, and output paths."
        )
        return 2
