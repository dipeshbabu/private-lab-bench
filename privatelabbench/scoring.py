"""Explicitly approved local numeric models; this executor is not a sandbox."""

from __future__ import annotations

from abc import ABC, abstractmethod
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from privatelabbench.external_validation import model_metadata, validate_profile
from privatelabbench.privacy.export import atomic_write_json

MANIFEST_SCHEMA = "model-manifest/v1"
ADAPTER_ID = "plb.linear-json"
ADAPTER_VERSION = "1.0.0"
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_FEATURE_VALUES = 20_000_000


def _object(value: Any, required, optional=(), *, label="manifest"):
    if (
        not isinstance(value, Mapping)
        or not set(required) <= set(value)
        or set(value) - set(required) - set(optional)
    ):
        raise ValueError(f"Unsupported or incomplete {label} fields")
    return dict(value)


def _local_path(value: Any, *, base: Path) -> Path:
    if (
        not isinstance(value, str)
        or not value.strip()
        or "://" in value
        or value.startswith(("\\\\", "//"))
    ):
        raise ValueError(
            "Only explicitly named local files are supported; network fetching is disabled"
        )
    path = Path(value)
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def validate_manifest(value: Any) -> dict:
    manifest = _object(
        value,
        {
            "schema_version",
            "trust",
            "model",
            "artifact",
            "adapter",
            "task_type",
            "features",
            "sample_id_column",
            "preprocessing",
            "postprocessing",
            "permissions",
            "deterministic",
        },
        {"input_dataset_version", "provenance"},
    )
    if (
        manifest["schema_version"] != MANIFEST_SCHEMA
        or manifest["trust"] != "approved_local"
    ):
        raise ValueError(
            "Only explicitly approved local models are supported; an untrusted isolated executor is not implemented"
        )
    model_metadata(manifest["model"])
    artifact = _object(
        manifest["artifact"], {"path", "sha256", "format"}, label="artifact"
    )
    if (
        artifact["format"] != "numeric-json/v1"
        or artifact["sha256"] != manifest["model"]["artifact_sha256"]
    ):
        raise ValueError(
            "Numeric JSON and matching immutable model/artifact digests are required"
        )
    if manifest["adapter"] != {"id": ADAPTER_ID, "version": ADAPTER_VERSION}:
        raise ValueError(
            "Unapproved adapter or version; remote/custom code and executable submissions are unsupported"
        )
    if manifest["task_type"] not in {"regression", "classification"}:
        raise ValueError(
            "The reference scorer supports explicit regression or binary classification"
        )
    if (
        not isinstance(manifest["permissions"], Mapping)
        or manifest["permissions"].get("network") is not False
        or manifest["permissions"]
        != {
            "network": False,
            "filesystem": "declared_local_io",
            "execution": "trusted_in_process",
        }
        or manifest["deterministic"] is not True
    ):
        raise ValueError(
            "Declare deterministic trusted execution with no network and only declared local input/output"
        )
    # These declarations constrain the built-in implementation, not installed Python libraries.
    if (
        not isinstance(manifest["sample_id_column"], str)
        or not manifest["sample_id_column"].strip()
    ):
        raise ValueError("A stable sample-ID column is required")
    features = manifest["features"]
    if not isinstance(features, list) or not 1 <= len(features) <= 10_000:
        raise ValueError("Declare between 1 and 10000 ordered features")
    names = []
    for feature in features:
        feature = _object(feature, {"name", "unit", "dtype"}, label="feature schema")
        if (
            any(
                not isinstance(feature[key], str) or not feature[key].strip()
                for key in ("name", "unit")
            )
            or feature["dtype"] != "float64"
        ):
            raise ValueError(
                "Features require named units and float64 dtype; missing values are rejected"
            )
        names.append(feature["name"])
    if len(set(names)) != len(names) or manifest["sample_id_column"] in names:
        raise ValueError("Feature names must be unique and separate from sample IDs")
    preprocessing = _object(
        manifest["preprocessing"], {"version", "missing_values"}, label="preprocessing"
    )
    if (
        preprocessing["version"] not in {"identity/v1", "standardize/v1"}
        or preprocessing["missing_values"] != "reject"
    ):
        raise ValueError(
            "Only versioned identity/standardization with reject-missing semantics is supported"
        )
    expected_post = (
        {"version": "identity/v1", "class_labels": []}
        if manifest["task_type"] == "regression"
        else {"version": "sigmoid/v1", "class_labels": ["0", "1"]}
    )
    if manifest["postprocessing"] != expected_post:
        raise ValueError(
            "Task/postprocessing mismatch; binary outputs require sigmoid probabilities for ordered labels 0,1"
        )
    if "input_dataset_version" in manifest and (
        not isinstance(manifest["input_dataset_version"], str)
        or not manifest["input_dataset_version"].strip()
    ):
        raise ValueError("Input dataset version must be a nonempty explicit label")
    if "provenance" in manifest and (
        not isinstance(manifest["provenance"], str)
        or len(manifest["provenance"]) > 2000
    ):
        raise ValueError(
            "Declared model provenance must be bounded text and remains local"
        )
    return manifest


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repeated model JSON keys are not supported")
        result[key] = value
    return result


def _numeric(values, *, shape):
    array = np.asarray(values)
    if array.dtype.kind not in "iuf" or array.shape != shape:
        raise ValueError("Model parameters must have the declared numeric shape")
    array = array.astype(np.float64)
    if not np.isfinite(array).all():
        raise ValueError("Model parameters must be finite")
    return array


class TrustedModelAdapter(ABC):
    """Versioned local adapter boundary; installing an adapter grants process trust.

    A future isolated executor needs independently enforced filesystem/egress/resource
    controls. This in-process interface provides no such isolation and never dispatches
    untrusted or manifest-specified Python modules.
    """

    id: str
    version: str
    api_version = "trusted-model-adapter/v1"

    @abstractmethod
    def load(self, artifact: bytes, manifest: Mapping[str, Any]) -> Any: ...

    @abstractmethod
    def predict(
        self, model: Any, features: np.ndarray, manifest: Mapping[str, Any]
    ) -> np.ndarray: ...


class LinearJSONAdapter(TrustedModelAdapter):
    id = ADAPTER_ID
    version = ADAPTER_VERSION

    def load(self, artifact, manifest):
        model = _object(
            json.loads(artifact, object_pairs_hook=_unique_json),
            {"schema_version", "feature_names", "coefficients", "intercept"},
            {"mean", "scale"},
            label="numeric model",
        )
        names = [feature["name"] for feature in manifest["features"]]
        if (
            model["schema_version"] != "linear-model/v1"
            or model["feature_names"] != names
        ):
            raise ValueError(
                "Model feature names/order do not match the approved manifest"
            )
        n = len(names)
        parameters = {
            "coefficients": _numeric(model["coefficients"], shape=(n,)),
            "intercept": _numeric(model["intercept"], shape=()),
        }
        if manifest["preprocessing"]["version"] == "standardize/v1":
            if not {"mean", "scale"} <= set(model):
                raise ValueError(
                    "Standardization requires frozen training means/scales"
                )
            parameters.update(
                {
                    "mean": _numeric(model["mean"], shape=(n,)),
                    "scale": _numeric(model["scale"], shape=(n,)),
                }
            )
            if np.any(parameters["scale"] <= 0):
                raise ValueError("Standardization scales must be positive")
        elif "mean" in model or "scale" in model:
            raise ValueError(
                "Identity preprocessing cannot silently ignore model standardization"
            )
        return parameters

    def predict(self, model, features, manifest):
        if "mean" in model:
            features = (features - model["mean"]) / model["scale"]
        with np.errstate(over="ignore", invalid="ignore"):
            result = features @ model["coefficients"] + model["intercept"]
        if not np.isfinite(result).all():
            raise ValueError("Model inference produced nonfinite values")
        if manifest["task_type"] == "classification":
            # Stable sigmoid without overflowing exp for large negative logits.
            positive = result >= 0
            probabilities = np.empty_like(result)
            probabilities[positive] = 1 / (1 + np.exp(-result[positive]))
            exponent = np.exp(result[~positive])
            probabilities[~positive] = exponent / (1 + exponent)
            result = probabilities
        return result


def _read_bounded(path: Path, maximum: int) -> bytes:
    with path.open("rb") as handle:
        content = handle.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError(
            "Declared local input exceeds the reference scorer resource limit"
        )
    return content


def score_local(
    manifest_path: str | Path,
    data_path: str | Path,
    output_path: str | Path,
    *,
    data_units: Mapping[str, str],
    dataset_version: str | None = None,
    target_column: str | None = None,
) -> dict[str, Any]:
    """Score approved local data. Features, logs, and IDs are never public outputs."""
    source = Path(manifest_path).resolve()
    manifest_bytes = _read_bounded(source, MAX_ARTIFACT_BYTES)
    raw = yaml.safe_load(manifest_bytes)
    manifest = validate_manifest(raw)
    artifact_path = _local_path(manifest["artifact"]["path"], base=source.parent)
    data = _local_path(str(data_path), base=Path.cwd())
    output = _local_path(str(output_path), base=Path.cwd())
    provenance = output.with_suffix(".score.json")
    protected = {source, artifact_path, data}
    if any(path in protected for path in (output, provenance)) or output == provenance:
        raise ValueError("Scoring outputs must be separate from all input files")
    if output.exists() or provenance.exists():
        raise ValueError("Scoring output already exists; choose fresh paths")
    expected_units = {
        feature["name"]: feature["unit"] for feature in manifest["features"]
    }
    if data_units != expected_units:
        raise ValueError(
            "Declared data units must exactly match every model feature; no implicit unit conversion"
        )
    if (
        manifest.get("input_dataset_version") is not None
        and dataset_version != manifest["input_dataset_version"]
    ):
        raise ValueError("Input dataset version differs from the approved manifest")
    artifact = _read_bounded(artifact_path, MAX_ARTIFACT_BYTES)
    if sha256(artifact).hexdigest() != manifest["artifact"]["sha256"]:
        raise ValueError("Model artifact digest mismatch")
    adapter = LinearJSONAdapter()
    model = adapter.load(artifact, manifest)
    content = _read_bounded(data, MAX_INPUT_BYTES)
    sample = manifest["sample_id_column"]
    frame = pd.read_csv(BytesIO(content), dtype={sample: "string"})
    names = list(expected_units)
    if not {sample, *names} <= set(frame) or frame.empty:
        raise ValueError(
            "Input is missing declared feature/sample-ID columns or contains no observations"
        )
    ids = frame[sample]
    if ids.isna().any() or ids.str.strip().eq("").any() or ids.duplicated().any():
        raise ValueError("Stable sample IDs must be complete and unique")
    if len(frame) * len(names) > MAX_FEATURE_VALUES:
        raise ValueError("Feature matrix exceeds the reference scorer resource limit")
    selected = frame[names]
    if any(pd.api.types.is_bool_dtype(selected[name]) for name in names):
        raise ValueError("Boolean features do not satisfy the float64 feature schema")
    features = selected.apply(pd.to_numeric, errors="raise").to_numpy(dtype=np.float64)
    if not np.isfinite(features).all():
        raise ValueError("Missing or nonfinite model inputs are rejected")
    predictions = np.asarray(adapter.predict(model, features, manifest), dtype=float)
    if predictions.shape != (len(frame),) or not np.isfinite(predictions).all():
        raise ValueError(
            "Adapter must return one finite prediction per stable sample ID"
        )
    if manifest["task_type"] == "classification" and (
        np.any(predictions < 0) or np.any(predictions > 1)
    ):
        raise ValueError("Adapter returned invalid positive-class probabilities")
    result = pd.DataFrame({"sample_id": ids, "prediction": predictions})
    if target_column:
        if (
            target_column in {sample, *names}
            or target_column not in frame
            or frame[target_column].isna().any()
        ):
            raise ValueError(
                "Evaluation target must be a separate, complete declared input column"
            )
        target = pd.to_numeric(frame[target_column], errors="raise").to_numpy(
            dtype=float
        )
        if not np.isfinite(target).all():
            raise ValueError("Evaluation targets must be finite")
        if manifest["task_type"] == "classification":
            if not set(np.unique(target)) <= {0.0, 1.0}:
                raise ValueError(
                    "The binary reference model requires numeric zero/one targets"
                )
            target = target.astype(int)
        result["target"] = target
    from privatelabbench.core.local_io import atomic_write_csv

    atomic_write_csv(output, result)
    info = {
        "schema_version": "local-scoring-provenance/v1",
        "scope": "local",
        "model": manifest["model"],
        "manifest_sha256": sha256(manifest_bytes).hexdigest(),
        "adapter": manifest["adapter"],
        "task_type": manifest["task_type"],
        "class_labels": manifest["postprocessing"]["class_labels"],
        "input_sha256": sha256(content).hexdigest(),
        "input_dataset_version": dataset_version,
        "prediction_sha256": sha256(output.read_bytes()).hexdigest(),
        "n_samples": len(result),
        "permissions": manifest["permissions"],
        "deterministic": True,
        "isolation": "none_trusted_in_process",
        "features": manifest["features"],
    }
    atomic_write_json(provenance, info)
    return {"predictions": str(output), "provenance": str(provenance), **info}


def evaluate_scored(
    summary, output_dir, protocol, *, release_policy=None, validation_profile=None
):
    """Opt-in reuse of normal evaluation and its central release boundary."""
    from privatelabbench.evaluate import make_evaluation_config
    from privatelabbench.runner import run_config
    from privatelabbench.protocols import resolve_protocol

    definition = resolve_protocol(protocol)
    if (
        definition.as_dict()["task_type"] != summary["task_type"]
        or definition.as_dict()["input_schema"]["class_labels"]
        != summary["class_labels"]
    ):
        raise ValueError(
            "Scored model task/class order conflicts with the evaluation protocol"
        )
    context = validation_profile or {
        "schema_version": "external-validation-profile/v1",
        "model": summary["model"],
        "dataset": {"visibility": "undisclosed", "training_overlap": "unknown"},
        "evaluator_relationship": "undisclosed",
    }
    context = validate_profile(context)
    if context["model"] != summary["model"]:
        raise ValueError("Validation profile must identify the exact scored model")
    output = Path(output_dir).resolve()
    config = output / "scored-evaluation.yaml"
    if output.exists() and any(output.iterdir()):
        raise ValueError(
            "Scored evaluation directory must be empty; choose fresh output paths"
        )
    settings = make_evaluation_config(
        summary["predictions"],
        output_dir=output,
        protocol=protocol,
        target="target",
        prediction_column="prediction",
        release_policy=release_policy,
    )
    settings["external_validation"] = context
    settings["scoring_provenance"] = {
        key: value
        for key, value in summary.items()
        if key not in {"predictions", "provenance"}
    }
    output.mkdir(parents=True, exist_ok=True)
    config.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
    return run_config(str(config))


def score_command(args) -> int:
    """CLI orchestration keeps input files separate and invalidates old exports first."""
    public = markdown = None
    try:
        protected = {
            Path(path).resolve()
            for path in (
                args.model,
                args.data,
                args.units,
                args.release_policy,
                args.validation_profile,
            )
            if path
        }
        if args.protocol and not args.protocol.startswith("plb://"):
            protected.add(Path(args.protocol).resolve())
        model_path = Path(args.model).resolve()
        manifest_error = None
        try:
            raw = yaml.safe_load(_read_bounded(model_path, MAX_ARTIFACT_BYTES))
        except (ValueError, OSError, yaml.YAMLError) as exc:
            raw, manifest_error = None, exc
        if isinstance(raw, dict) and isinstance(raw.get("artifact"), dict):
            try:
                protected.add(
                    _local_path(raw["artifact"].get("path"), base=model_path.parent)
                )
            except ValueError as exc:
                manifest_error = exc
        prediction_output = Path(args.output).resolve()
        scoring_outputs = {
            prediction_output,
            prediction_output.with_suffix(".score.json"),
        }
        if scoring_outputs & protected:
            raise ValueError(
                "Scoring outputs must preserve every model/data/policy/protocol input"
            )
        if args.evaluate_output_dir:
            folder = Path(args.evaluate_output_dir).resolve()
            public, markdown = (
                folder / "evaluation_receipt.shareable.json",
                folder / "evaluation_receipt.md",
            )
            related = {
                folder / name
                for name in (
                    "evaluation.json",
                    "evaluation.md",
                    "evaluation_manifest.json",
                    "audit.jsonl",
                    "evaluation_receipt.json",
                    "evaluation_receipt.shareable.json",
                    "evaluation_receipt.md",
                    "scored-evaluation.yaml",
                    "evaluation_receipt.shareable.release-audit.json",
                    ".plb-release-ledger.json",
                    ".plb-release.lock",
                )
            }
            if related & (protected | scoring_outputs):
                # Never remove a colliding source, including on the exception path.
                public = markdown = None
                raise ValueError(
                    "Evaluation outputs must preserve every scoring input and prediction output"
                )
            public.unlink(missing_ok=True)
            markdown.unlink(missing_ok=True)
            if not args.target or not args.protocol:
                raise ValueError(
                    "The evaluation pipeline requires explicit --target and --protocol"
                )
        elif any((args.protocol, args.release_policy, args.validation_profile)):
            raise ValueError("Evaluation options require --evaluate-output-dir")
        if manifest_error is not None:
            raise manifest_error
        summary = score_local(
            args.model,
            args.data,
            args.output,
            data_units=yaml.safe_load(Path(args.units).read_text(encoding="utf-8")),
            dataset_version=args.data_version,
            target_column=args.target,
        )
        if args.evaluate_output_dir:
            evaluation = evaluate_scored(
                summary,
                args.evaluate_output_dir,
                args.protocol,
                release_policy=(
                    yaml.safe_load(
                        Path(args.release_policy).read_text(encoding="utf-8")
                    )
                    if args.release_policy
                    else None
                ),
                validation_profile=(
                    yaml.safe_load(
                        Path(args.validation_profile).read_text(encoding="utf-8")
                    )
                    if args.validation_profile
                    else None
                ),
            )
            print(f"Evaluation report: {evaluation['json_report']}")
        print(
            f"Scored {summary['n_samples']} observations with {summary['model']['id']}@{summary['model']['revision']}"
        )
        print(f"Local predictions: {summary['predictions']}")
        print(f"Local provenance: {summary['provenance']}")
        return 0
    except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError) as exc:
        for path in (public, markdown):
            if path is not None:
                path.unlink(missing_ok=True)
        print(f"Local scoring rejected: {exc}")
        return 2
