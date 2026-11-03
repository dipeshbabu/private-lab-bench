"""Pinned public ADMET snapshots, aligned predictions, and ordinary PLB receipts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from privatelabbench.core.local_io import atomic_write_csv as _write_csv
from privatelabbench.privacy.export import atomic_write_json

REFERENCE_VERSION = "0.4.1"
ARCHIVE_ID = "4426004"
ARCHIVE_SHA256 = "bd0005246cb6f1672333c28ad202112a8bf071ab65d847848715030308faf1f1"
BENCHMARK_VERSION = "admet-4426004-bd0005246cb6"
SOURCE_URL = "https://tdcommons.ai/benchmark/admet_group/overview/"


@dataclass(frozen=True)
class TDCTask:
    id: str
    task_type: str
    metric: str
    upstream_metric: str
    train_val_sha256: str
    test_sha256: str

    @property
    def protocol(self) -> str:
        return f"plb://tdc/admet/{self.id.replace('_', '-')}@1.0.0"


TASKS = {
    "caco2_wang": TDCTask(
        "caco2_wang",
        "regression",
        "mae",
        "mae",
        "e0965b4a0617a3aa2978ef28794e3467d55655090f282a120355ea575ebed6b2",
        "5380c15b0dd9c11e22d3e3843083362d535dae36062dfee08056d3af4cb444df",
    ),
    "pgp_broccatelli": TDCTask(
        "pgp_broccatelli",
        "classification",
        "auroc",
        "roc-auc",
        "4a9183cf40c01881c6cfdeee7b68fed6dbe31348081099a323b9b76351a1dae0",
        "959e448d2b8927d65ede864838c2eee5b2075d4c01ca544aeec4c90d663b4ccb",
    ),
    "ames": TDCTask(
        "ames",
        "classification",
        "auroc",
        "roc-auc",
        "8b3add847978ec60685541e07696c837f116b7cb245d44f86eb8f4f69da8e44d",
        "d87e29ad1f188d6ee4fcdd5c3c3aa4ba15e4fec657553353d0d951ad8df02d3f",
    ),
    "herg": TDCTask(
        "herg",
        "classification",
        "auroc",
        "roc-auc",
        "22fc4c4b6079f72b392cf2ae675d99c6927a6351377ee50c4f9f98c586a3f206",
        "14277bd932dce885e2f7a8d706effb455816f983e05b230f4f1c9590eb6c4248",
    ),
    "lipophilicity_astrazeneca": TDCTask(
        "lipophilicity_astrazeneca",
        "regression",
        "mae",
        "mae",
        "a54636f85cf31eb4c914ea15e2c3a15364b0b8b51986262ea229203637e08f31",
        "69f3870c9b6f2cec79a992a31d59d2e940962f7e2c4b27dabaed1fe1e767e2d8",
    ),
    "solubility_aqsoldb": TDCTask(
        "solubility_aqsoldb",
        "regression",
        "mae",
        "mae",
        "adbee092423fe0cb0f4219520f2f93730b6ba5bb1d0ef8dd7764c2d32b3393b9",
        "18cd02deec4e06c611a6e7e38fb44a1731bc0c0a96bc5d4ded098ff29da645fe",
    ),
}


def get_task(name: str) -> TDCTask:
    try:
        return TASKS[name.strip().lower()]
    except KeyError as exc:
        raise ValueError(
            f"Supported TDC subset: {', '.join(TASKS)}; unsupported official metrics are never replaced with generic ones"
        ) from exc


@dataclass(frozen=True)
class TDCBenchmark:
    task: TDCTask
    root: Path
    train_val: pd.DataFrame = field(repr=False, compare=False)
    test: pd.DataFrame = field(repr=False, compare=False)

    def identity(self) -> dict[str, str]:
        return {
            "id": f"tdc-{self.task.id.replace('_', '-')}",
            "version": BENCHMARK_VERSION,
            "suite": "tdc-admet-group",
            "domain": "therapeutics",
            "protocol": "prediction-table/v1",
        }


def partition_table(
    frame: pd.DataFrame, task: TDCTask, partition: str, *, predictions: Any = None
) -> pd.DataFrame:
    """Ordinal IDs preserve measurements when upstream Drug_ID/SMILES repeat."""
    if not {"Drug_ID", "Drug", "Y"} <= set(frame):
        raise ValueError("TDC partitions require Drug_ID, Drug, and Y columns")
    y = pd.to_numeric(frame["Y"], errors="raise").to_numpy(dtype=float)
    if not len(y) or not np.isfinite(y).all() or frame["Drug"].isna().any():
        raise ValueError(
            "Official TDC partitions require complete finite targets and molecules"
        )
    if task.task_type == "classification":
        if not set(np.unique(y)) <= {0.0, 1.0}:
            raise ValueError("TDC binary labels must be numeric zero/one")
        y = y.astype(int)
    output = pd.DataFrame(
        {
            "sample_id": [
                f"tdc-{task.id}-{partition}-{index:06d}" for index in range(len(frame))
            ],
            "target": y,
            "smiles": frame["Drug"].astype(str).to_numpy(),
            "upstream_drug_id": frame["Drug_ID"].astype(str).to_numpy(),
        }
    )
    if predictions is not None:
        p = np.asarray(predictions, dtype=float)
        if p.ndim != 1 or len(p) != len(y) or not np.isfinite(p).all():
            raise ValueError(
                "Exactly one finite prediction is required for every official test record"
            )
        if task.task_type == "classification" and (np.any(p < 0) or np.any(p > 1)):
            raise ValueError(
                "The prediction-table profile requires positive-class probabilities between zero and one"
            )
        output["prediction"] = p
    return output


def _benchmark_directory(root: str | Path, task: TDCTask) -> Path:
    directory = Path(root).resolve()
    if (directory / "admet_group").is_dir():
        directory /= "admet_group"
    return directory / task.id


def load_benchmark(root: str | Path, dataset: str) -> TDCBenchmark:
    task = get_task(dataset)
    directory = _benchmark_directory(root, task)
    frames = []
    for filename, expected in (
        ("train_val.csv", task.train_val_sha256),
        ("test.csv", task.test_sha256),
    ):
        path = directory / filename
        if not path.is_file():
            raise FileNotFoundError(
                "Pinned TDC snapshot is missing; use tdc-prepare --download or provide an official cached ADMET group"
            )
        content = path.read_bytes()
        if sha256(content).hexdigest() != expected:
            raise ValueError(
                "TDC snapshot differs from the pinned official files; refusing silent data drift. Use ordinary plb evaluate for private ADMET tables"
            )
        frame = pd.read_csv(BytesIO(content))
        partition_table(frame, task, filename.removesuffix(".csv"))
        frames.append(frame)
    return TDCBenchmark(task, directory, *frames)


def download_benchmarks(root: str | Path) -> None:
    try:
        from tdc.benchmark_group import admet_group
    except ImportError as exc:
        raise ValueError(
            "Install the optional tdc extra in its documented clean environment to fetch upstream data"
        ) from exc
    directory = Path(root).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    group = admet_group(path=str(directory))
    if group.file_format != "csv":
        raise ValueError("This integration accepts data-only CSV benchmark snapshots")


def align_predictions(
    benchmark: TDCBenchmark,
    path: str | Path,
    *,
    prediction_column: str = "prediction",
    upstream_test_order: bool = False,
    prediction_bytes: bytes | None = None,
) -> pd.DataFrame:
    content = Path(path).read_bytes() if prediction_bytes is None else prediction_bytes
    frame = pd.read_csv(BytesIO(content), dtype={"sample_id": "string"})
    if prediction_column not in frame:
        raise ValueError("Prediction CSV is missing its declared prediction column")
    expected = partition_table(benchmark.test, benchmark.task, "test")
    if "sample_id" in frame:
        ids = frame["sample_id"]
        if ids.isna().any() or ids.duplicated().any():
            raise ValueError("Prediction sample IDs must be complete and unique")
        if set(ids) != set(expected.sample_id):
            raise ValueError(
                "Prediction IDs must exactly match the generated TDC test template; Drug_ID is not a unique record key"
            )
        frame = frame.set_index("sample_id").loc[expected.sample_id].reset_index()
    elif not upstream_test_order:
        raise ValueError(
            "Supply generated sample_id values, or explicitly declare --upstream-test-order for arrays in upstream test order"
        )
    if len(frame) != len(expected):
        raise ValueError("Prediction count differs from the fixed official test set")
    if "target" in frame:
        given = pd.to_numeric(frame.target, errors="raise").to_numpy(dtype=float)
        if not np.array_equal(given, expected.target.to_numpy(dtype=float)):
            raise ValueError(
                "Provided targets disagree with the pinned official test labels"
            )
    return partition_table(
        benchmark.test,
        benchmark.task,
        "test",
        predictions=pd.to_numeric(frame[prediction_column], errors="raise").to_numpy(),
    )


def prepare_template(
    root: str | Path, dataset: str, output: str | Path, *, download: bool = False
) -> dict[str, Any]:
    if download:
        download_benchmarks(root)
    benchmark = load_benchmark(root, dataset)
    target = Path(output)
    if target.exists():
        raise ValueError(
            "Template output already exists; choose another path to preserve predictions"
        )
    if target.resolve() in {
        benchmark.root.joinpath(name).resolve()
        for name in ("train_val.csv", "test.csv")
    }:
        raise ValueError("Choose a template output separate from the upstream data")
    frame = partition_table(benchmark.test, benchmark.task, "test")[["sample_id"]]
    frame["prediction"] = np.nan
    _write_csv(target, frame)
    return {
        "dataset": benchmark.task.id,
        "n_test": len(frame),
        "metric": benchmark.task.metric,
        "protocol": benchmark.task.protocol,
        "template": str(target),
    }


def evaluate_tdc(
    root: str | Path,
    dataset: str,
    predictions: str | Path,
    output_dir: str | Path,
    *,
    prediction_column: str = "prediction",
    upstream_test_order: bool = False,
    release_policy: Mapping[str, Any] | None = None,
    release_policy_path: str | Path | None = None,
) -> dict[str, Any]:
    from privatelabbench.runner import run_config

    output = Path(output_dir).resolve()
    directory = _benchmark_directory(root, get_task(dataset))
    canonical, config_path, provenance_path = (
        output / "predictions.csv",
        output / "evaluation.yaml",
        output / "tdc_input.json",
    )
    public = output / "evaluation_receipt.shareable.json"
    protected = {
        Path(predictions).resolve(),
        *[directory.joinpath(name).resolve() for name in ("train_val.csv", "test.csv")],
    }
    if release_policy_path is not None:
        protected.add(Path(release_policy_path).resolve())
    targets = [
        canonical,
        config_path,
        provenance_path,
        output / "evaluation.json",
        output / "evaluation.md",
        output / "evaluation_manifest.json",
        output / "audit.jsonl",
        output / "evaluation_receipt.json",
        public,
        output / "evaluation_receipt.md",
        public.with_suffix(".release-audit.json"),
        output / ".plb-release-ledger.json",
        output / ".plb-release.lock",
    ]
    if any(path.resolve() in protected for path in targets):
        raise ValueError("TDC output paths must be separate from every input file")
    public.unlink(missing_ok=True)
    (output / "evaluation_receipt.md").unlink(missing_ok=True)
    if release_policy_path is not None:
        if release_policy is not None:
            raise ValueError("Supply a release policy mapping or path, not both")
        release_policy = yaml.safe_load(
            Path(release_policy_path).read_text(encoding="utf-8")
        )
        if not isinstance(release_policy, Mapping):
            raise ValueError("Release policy must be a mapping")
    benchmark = load_benchmark(root, dataset)
    if canonical.exists() and not (
        provenance_path.is_file()
        and json.loads(provenance_path.read_text()).get("schema_version")
        == "tdc-evaluation-input/v1"
    ):
        raise ValueError(
            "Output directory contains an unrecognized prediction table; choose another directory"
        )
    if config_path.exists() and not config_path.read_text(encoding="utf-8").startswith(
        "# Generated by plb tdc-evaluate;"
    ):
        raise ValueError(
            "Output directory contains a manually authored config; choose another directory"
        )
    prediction_bytes = Path(predictions).read_bytes()
    frame = align_predictions(
        benchmark,
        predictions,
        prediction_column=prediction_column,
        upstream_test_order=upstream_test_order,
        prediction_bytes=prediction_bytes,
    )
    _write_csv(canonical, frame)
    input_info = {
        "schema_version": "tdc-evaluation-input/v1",
        "scope": "local",
        "dataset": benchmark.task.id,
        "benchmark_version": BENCHMARK_VERSION,
        "archive_id": ARCHIVE_ID,
        "archive_sha256": ARCHIVE_SHA256,
        "train_val_sha256": benchmark.task.train_val_sha256,
        "test_sha256": benchmark.task.test_sha256,
        "prediction_source": str(Path(predictions).resolve()),
        "prediction_source_sha256": sha256(prediction_bytes).hexdigest(),
        "upstream_test_order_declared": upstream_test_order,
        "n_train_val": len(benchmark.train_val),
        "n_test": len(benchmark.test),
        "metric": benchmark.task.metric,
        "upstream_metric": benchmark.task.upstream_metric,
        "source": SOURCE_URL,
    }
    atomic_write_json(provenance_path, input_info)
    config = {
        "project": f"tdc-{benchmark.task.id}",
        "protocol": benchmark.task.protocol,
        "benchmark": benchmark.identity(),
        "input": {
            "path": str(canonical),
            "sample_id_column": "sample_id",
            "target_column": "target",
            "prediction_column": "prediction",
        },
        "report": {
            "json": str(output / "evaluation.json"),
            "markdown": str(output / "evaluation.md"),
            "manifest": str(output / "evaluation_manifest.json"),
        },
        "audit": {"path": str(output / "audit.jsonl")},
        "tdc_provenance": input_info,
    }
    if release_policy is not None:
        config["release"] = dict(release_policy)
    config_path.write_text(
        "# Generated by plb tdc-evaluate; inputs remain local.\n"
        + yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )
    summary = run_config(str(config_path))
    summary["tdc"] = {
        "dataset": benchmark.task.id,
        "metric": benchmark.task.metric,
        "n_test": len(frame),
        "upstream_reference_metric": benchmark.task.upstream_metric,
    }
    return summary
