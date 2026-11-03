"""Pinned Matbench labels/folds and external predictions; no structure execution."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import yaml

from privatelabbench.core.local_io import atomic_write_csv
from privatelabbench.core.public_data import download_verified as _download
from privatelabbench.privacy.export import (
    _mapping,
    atomic_write_json,
    protocol_identity,
)
from privatelabbench.protocols import resolve_protocol
from privatelabbench.reports.integrity import attach_integrity_metadata

REFERENCE_COMMIT = "35f88110a51adf817a53515780d99fc34f614bf8"
REFERENCE_SCORER_SHA256 = (
    "f791263c675c45b6938c78d856676a6821ac6879526bc9aca7d82523303c3414"
)
FOLDS_FILE = "matbench_v0.1_validation.json"
FOLDS_SHA256 = "94c17bc3dac32c67d33d69289927a5fec174497e74bbc47293e23d3d147e9a6d"
BENCHMARK_VERSION = "matbench-v0.1-35f88110"
RESULT_SCHEMA = "matbench-evaluation/v1"


@dataclass(frozen=True)
class MatbenchTask:
    name: str
    task_type: str
    input_type: str
    target: str
    unit: str | None
    n_samples: int
    data_sha256: str
    test_sizes: tuple[int, ...]

    @property
    def metric(self):
        return "mae" if self.task_type == "regression" else "auroc"

    @property
    def upstream_metric(self):
        return "mae" if self.task_type == "regression" else "rocauc"

    @property
    def protocol(self):
        return f"plb://matbench/{self.name.removeprefix('matbench_').replace('_', '-')}@1.0.0"

    @property
    def filename(self):
        return self.name + ".json.gz"

    @property
    def url(self):
        return "https://ml.materialsproject.org/projects/" + self.filename

    def identity(self, fold=None):
        return {
            "id": self.name if fold is None else f"{self.name}-fold-{fold}",
            "version": BENCHMARK_VERSION,
            "suite": "matbench",
            "domain": "materials",
            "protocol": "prediction-table/v1",
        }


TASKS = {
    "matbench_steels": MatbenchTask(
        "matbench_steels",
        "regression",
        "composition",
        "yield strength",
        "MPa",
        312,
        "473bc4957b2ea5e6465aef84bc29bb48ac34db27d69ea4ec5f508745c6fae252",
        (63, 63, 62, 62, 62),
    ),
    "matbench_expt_is_metal": MatbenchTask(
        "matbench_expt_is_metal",
        "classification",
        "composition",
        "is_metal",
        None,
        4921,
        "8f2a4f9bacdcbc5c2c73615629ee7986f09d39bed40ba7db52b61b2889730887",
        (985, 984, 984, 984, 984),
    ),
    "matbench_jdft2d": MatbenchTask(
        "matbench_jdft2d",
        "regression",
        "structure",
        "exfoliation_en",
        "meV/atom",
        636,
        "26057dc4524e193e32abffb296ce819b58b6e11d1278cae329a2f97817a4eddf",
        (128, 127, 127, 127, 127),
    ),
    "matbench_expt_gap": MatbenchTask(
        "matbench_expt_gap",
        "regression",
        "composition",
        "gap expt",
        "eV",
        4604,
        "783e7d1461eb83b00b2f2942da4b95fda5e58a0d1ae26b581c24cf8a82ca75b2",
        (921, 921, 921, 921, 920),
    ),
    "matbench_glass": MatbenchTask(
        "matbench_glass",
        "classification",
        "composition",
        "gfa",
        None,
        5680,
        "36beb654e2a463ee2a6572105bea0ca2961eee7c7b26a25377bff2c3b338e53a",
        (1136, 1136, 1136, 1136, 1136),
    ),
}


def get_task(name):
    try:
        return TASKS[name.strip().lower()]
    except (KeyError, AttributeError) as exc:
        raise ValueError(
            f"Supported Matbench subset: {', '.join(TASKS)}; unsupported metrics/tasks are not substituted"
        ) from exc


def _verified_bytes(path, expected):
    content = Path(path).read_bytes()
    if sha256(content).hexdigest() != expected:
        raise ValueError(
            "Matbench snapshot differs from pinned official bytes; choose a fresh cache for modified/private data"
        )
    return content


def download_benchmark(root, dataset):
    task = get_task(dataset)
    root = Path(root).resolve()
    _download(
        root / FOLDS_FILE,
        f"https://raw.githubusercontent.com/materialsproject/matbench/{REFERENCE_COMMIT}/matbench/{FOLDS_FILE}",
        FOLDS_SHA256,
    )
    _download(root / task.filename, task.url, task.data_sha256)


@dataclass(frozen=True)
class MatbenchSnapshot:
    task: MatbenchTask
    labels: pd.DataFrame = field(repr=False, compare=False)
    folds: tuple[dict, ...] = field(repr=False, compare=False)


def load_snapshot(root, dataset):
    task = get_task(dataset)
    root = Path(root).resolve()
    data = json.loads(
        gzip.decompress(_verified_bytes(root / task.filename, task.data_sha256))
    )
    if (
        data.get("index") != list(range(task.n_samples))
        or len(data.get("data", [])) != task.n_samples
        or task.target not in data.get("columns", [])
    ):
        raise ValueError("Official row order, target, or task size differs")
    position = data["columns"].index(task.target)
    targets = np.asarray([row[position] for row in data["data"]], dtype=float)
    if not np.isfinite(targets).all():
        raise ValueError("Official targets must be finite; no rows are dropped")
    if task.task_type == "classification":
        if set(np.unique(targets)) != {0.0, 1.0}:
            raise ValueError("Official classification labels must be false/true")
        targets = targets.astype(int)
    prefix = task.name.replace("matbench", "mb").replace("_", "-")
    ids = [
        f"{prefix}-{index + 1:0{len(str(task.n_samples))}d}" for index in data["index"]
    ]
    labels = pd.DataFrame({"sample_id": ids, "target": targets}).set_index(
        "sample_id", drop=False
    )
    document = json.loads(_verified_bytes(root / FOLDS_FILE, FOLDS_SHA256))
    if document.get("metadata") != {
        "n_splits": 5,
        "random_state": 18012019,
        "shuffle": True,
    }:
        raise ValueError("Official five-fold definition changed")
    source = document["splits"][task.name]
    if set(source) != {f"fold_{index}" for index in range(5)}:
        raise ValueError("Exactly five official folds are required")
    folds = []
    seen = set()
    all_ids = set(ids)
    for index in range(5):
        split = source[f"fold_{index}"]
        train, test = split["train"], split["test"]
        if (
            len(test) != task.test_sizes[index]
            or len(set(test)) != len(test)
            or len(set(train)) != len(train)
            or set(train) & set(test)
            or set(train) | set(test) != all_ids
            or seen & set(test)
        ):
            raise ValueError(
                "Official fold identity/coverage differs; resplitting is not supported"
            )
        seen.update(test)
        folds.append({"fold": index, "train": tuple(train), "test": tuple(test)})
    if seen != all_ids:
        raise ValueError("Official test folds must cover every record exactly once")
    return MatbenchSnapshot(task, labels, tuple(folds))


def prepare_template(root, dataset, output, *, download=False):
    if download:
        download_benchmark(root, dataset)
    snapshot = load_snapshot(root, dataset)
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Choose a fresh Matbench template path")
    rows = [
        {"fold": fold["fold"], "sample_id": sample, "prediction": np.nan}
        for fold in snapshot.folds
        for sample in fold["test"]
    ]
    atomic_write_csv(output, pd.DataFrame(rows))
    return {
        "dataset": snapshot.task.name,
        "n_samples": len(rows),
        "folds": 5,
        "template": str(output),
        "metric": snapshot.task.metric,
    }


def align_predictions(snapshot, content, prediction_column="prediction"):
    frame = pd.read_csv(BytesIO(content), dtype={"sample_id": "string"})
    if not {"fold", "sample_id", prediction_column} <= set(frame) or set(frame) - {
        "fold",
        "sample_id",
        prediction_column,
        "target",
    }:
        raise ValueError(
            "Matbench predictions require fold, sample_id, and one score; optional targets must match"
        )
    if frame.sample_id.isna().any() or frame.sample_id.duplicated().any():
        raise ValueError(
            "Official sample IDs must be complete and unique across test folds"
        )
    fold_values = pd.to_numeric(frame["fold"], errors="raise").to_numpy(dtype=float)
    if (
        not np.isfinite(fold_values).all()
        or not np.array_equal(fold_values, np.floor(fold_values))
        or set(fold_values) != {0, 1, 2, 3, 4}
    ):
        raise ValueError("Provide complete official folds 0 through 4")
    frame["fold"] = fold_values.astype(int)
    predictions = pd.to_numeric(frame[prediction_column], errors="raise").to_numpy(
        dtype=float
    )
    if (
        not np.isfinite(predictions).all()
        or snapshot.task.task_type == "classification"
        and (np.any(predictions < 0) or np.any(predictions > 1))
    ):
        raise ValueError(
            "Predictions must be finite; metallicity scores must be probabilities of true"
        )
    outputs = []
    for fold in snapshot.folds:
        selected = frame[frame.fold == fold["fold"]]
        if set(selected.sample_id) != set(fold["test"]):
            raise ValueError("Predictions do not match official fold/sample membership")
        selected = selected.set_index("sample_id").loc[list(fold["test"])]
        expected = snapshot.labels.loc[list(fold["test"])]
        if "target" in selected and not np.array_equal(
            pd.to_numeric(selected.target, errors="raise").to_numpy(dtype=float),
            expected.target.to_numpy(dtype=float),
        ):
            raise ValueError("Submission targets differ from pinned official labels")
        output = expected.copy().reset_index(drop=True)
        output["prediction"] = pd.to_numeric(
            selected[prediction_column], errors="raise"
        ).to_numpy(dtype=float)
        outputs.append(output)
    return tuple(outputs)


def evaluate_matbench(
    root,
    dataset,
    predictions,
    output_dir,
    *,
    prediction_column="prediction",
    release_policy_path=None,
):
    from privatelabbench.privacy.export import publish_shareable_artifact
    from privatelabbench.runner import run_config

    output = Path(output_dir).resolve()
    result_path = output / "matbench_result.json"
    public = output / "matbench_result.shareable.json"
    markdown = output / "matbench_result.md"
    sources = {
        Path(predictions).resolve(),
        Path(root).resolve() / FOLDS_FILE,
        *[Path(root).resolve() / task.filename for task in TASKS.values()],
    }
    if release_policy_path:
        sources.add(Path(release_policy_path).resolve())
    targets = {
        result_path,
        public,
        markdown,
        public.with_suffix(".release-audit.json"),
        output / ".plb-release-ledger.json",
        output / ".plb-release.lock",
    }
    for index in range(5):
        targets.update(
            output / f"fold-{index}" / name
            for name in (
                "predictions.csv",
                "evaluation.yaml",
                "evaluation.json",
                "evaluation.md",
                "evaluation_manifest.json",
                "evaluation_receipt.json",
                "evaluation_receipt.shareable.json",
                "evaluation_receipt.md",
                "audit.jsonl",
                "evaluation_receipt.shareable.release-audit.json",
                ".plb-release-ledger.json",
                ".plb-release.lock",
            )
        )
    if targets & sources:
        raise ValueError(
            "Matbench outputs must preserve every cache, prediction, and policy input"
        )
    public.unlink(missing_ok=True)
    markdown.unlink(missing_ok=True)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose an empty Matbench evaluation directory")
    policy = (
        yaml.safe_load(Path(release_policy_path).read_text(encoding="utf-8"))
        if release_policy_path
        else None
    )
    snapshot = load_snapshot(root, dataset)
    content = Path(predictions).read_bytes()
    frames = align_predictions(snapshot, content, prediction_column)
    task = snapshot.task
    records = []
    references = []
    for fold, frame in zip(snapshot.folds, frames):
        folder = output / f"fold-{fold['fold']}"
        table = folder / "predictions.csv"
        atomic_write_csv(table, frame)
        settings = {
            "project": task.name,
            "protocol": task.protocol,
            "benchmark": task.identity(fold["fold"]),
            "input": {
                "path": str(table),
                "sample_id_column": "sample_id",
                "target_column": "target",
                "prediction_column": "prediction",
            },
            "report": {
                "json": str(folder / "evaluation.json"),
                "markdown": str(folder / "evaluation.md"),
                "manifest": str(folder / "evaluation_manifest.json"),
            },
            "audit": {"path": str(folder / "audit.jsonl")},
            "matbench_local": {
                "dataset": task.name,
                "fold": fold["fold"],
                "target_unit": task.unit,
                "upstream_metric": task.upstream_metric,
                "data_sha256": task.data_sha256,
                "fold_definition_sha256": FOLDS_SHA256,
                "reference_commit": REFERENCE_COMMIT,
            },
        }
        config = folder / "evaluation.yaml"
        config.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
        summary = run_config(str(config))
        score = float(summary["reported_metrics"][task.metric])
        records.append(
            {
                "fold": fold["fold"],
                "n_train": len(fold["train"]),
                "n_test": len(fold["test"]),
                "score": score,
            }
        )
        references.append(
            {
                "fold": fold["fold"],
                "receipt": str(folder / "evaluation_receipt.json"),
                "receipt_payload_sha256": json.loads(
                    (folder / "evaluation_receipt.json").read_text()
                )["integrity"]["payload_sha256"],
            }
        )
    definition = resolve_protocol(task.protocol)
    values = [row["score"] for row in records]
    shared = {
        "dataset": task.name,
        "benchmark": task.identity(),
        "protocol": definition.identity(),
        "task_type": task.task_type,
        "input_type": task.input_type,
        "target_unit": task.unit,
        "metric": task.metric,
        "upstream_metric": task.upstream_metric,
        "folds": records,
        "metrics": {task.metric: float(np.mean(values))},
        "fold_score_statistics": {
            "mean": float(np.mean(values)),
            "std": float(np.std(values)),
            "min": float(np.min(values)),
            "max": float(np.max(values)),
        },
        "aggregation": "unweighted_mean_of_five_official_fold_scores",
        "uncertainty_scope": "across_fold_standard_deviation_not_population_ci",
        "reference_commit": REFERENCE_COMMIT,
        "classification_semantics": (
            "probability_roc_auc_corrected"
            if task.task_type == "classification"
            else "not_applicable"
        ),
    }
    artifact = attach_integrity_metadata(
        {
            "schema_version": RESULT_SCHEMA,
            "evaluation_id": str(uuid4()),
            "scope": "local",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "shareable": shared,
            "local": {
                "cache": str(Path(root).resolve()),
                "prediction_source": str(Path(predictions).resolve()),
                "prediction_sha256": sha256(content).hexdigest(),
                "data_sha256": task.data_sha256,
                "fold_definition_sha256": FOLDS_SHA256,
                "fold_receipts": references,
                "protocol_definition": definition.as_dict(),
                "reference_scorer_sha256": REFERENCE_SCORER_SHA256,
            },
        }
    )
    atomic_write_json(result_path, artifact)
    decision = publish_shareable_artifact(artifact, policy, public)
    if decision.decision == "allow":
        markdown.write_text(
            render_result(json.loads(public.read_text(encoding="utf-8"))),
            encoding="utf-8",
        )
    return {
        "artifact": artifact,
        "local_result": str(result_path),
        "release": decision.as_dict(),
        "shareable_result": str(public) if decision.decision == "allow" else None,
    }


def sanitize_result(value, policy):
    shared = _mapping(value)
    task = get_task(shared.get("dataset"))
    definition = resolve_protocol(task.protocol)
    if (
        protocol_identity(shared.get("protocol")) != definition.identity()
        or shared.get("benchmark") != task.identity()
        or policy.get("public_benchmark") != task.identity()
        or not policy.get("include_protocol")
    ):
        raise ValueError("Approve the exact Matbench snapshot and protocol identities")
    if (
        shared.get("metric") != task.metric
        or shared.get("target_unit") != task.unit
        or shared.get("reference_commit") != REFERENCE_COMMIT
    ):
        raise ValueError(
            "Matbench metric/unit/reference differs from the pinned contract"
        )
    rows = shared.get("folds")
    if not isinstance(rows, list) or len(rows) != 5:
        raise ValueError("Five complete fold scores are required")
    minimum = max(
        policy["min_samples"],
        policy["min_cell_size"],
        definition.as_dict()["release"]["min_samples"],
        definition.as_dict()["release"]["min_cell_size"],
    )
    clean = []
    seen = set()
    for row in rows:
        row = _mapping(row)
        fold = row.get("fold")
        score = row.get("score")
        if (
            type(fold) is not int
            or fold not in range(5)
            or fold in seen
            or type(score) not in {float, int}
            or not np.isfinite(score)
            or task.metric == "mae"
            and score < 0
            or task.metric == "auroc"
            and not 0 <= score <= 1
        ):
            raise ValueError("Invalid Matbench fold score")
        n = task.test_sizes[fold]
        if (
            row.get("n_test") != n
            or row.get("n_train") != task.n_samples - n
            or n < minimum
        ):
            raise ValueError("Every official test fold must satisfy release counts")
        seen.add(fold)
        clean.append(
            {
                "fold": fold,
                "n_train": task.n_samples - n,
                "n_test": n,
                "score": float(score),
            }
        )
    clean.sort(key=lambda row: row["fold"])
    values = [row["score"] for row in clean]
    return {
        "dataset": task.name,
        "benchmark": task.identity(),
        "protocol": definition.identity(),
        "task_type": task.task_type,
        "input_type": task.input_type,
        "target_unit": task.unit,
        "metric": task.metric,
        "upstream_metric": task.upstream_metric,
        "folds": clean,
        "metrics": {task.metric: float(np.mean(values))},
        "fold_score_statistics": {
            "mean": float(np.mean(values)),
            "std": float(np.std(values)),
            "min": float(np.min(values)),
            "max": float(np.max(values)),
        },
        "aggregation": "unweighted_mean_of_five_official_fold_scores",
        "uncertainty_scope": "across_fold_standard_deviation_not_population_ci",
        "reference_commit": REFERENCE_COMMIT,
        "classification_semantics": (
            "probability_roc_auc_corrected"
            if task.task_type == "classification"
            else "not_applicable"
        ),
    }


def render_result(artifact):
    shared = artifact["shareable"]
    lines = [
        "# Matbench evaluation",
        "",
        f"Dataset: {shared['dataset']}; metric: {shared['metric']}; target unit: {shared['target_unit'] or 'binary class'}",
        "",
        "| Fold | Train records | Test records | Score |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in shared["folds"]:
        lines.append(
            f"| {row['fold']} | {row['n_train']} | {row['n_test']} | {row['score']:.8g} |"
        )
    stats = shared["fold_score_statistics"]
    lines.extend(
        [
            "",
            f"Official unweighted fold mean: {stats['mean']:.8g}; fold standard deviation: {stats['std']:.8g}.",
            "Fold variation is not a population confidence interval. Classification uses corrected probability ROC-AUC, not historical thresholded leaderboard ROC-AUC.",
        ]
    )
    return "\n".join(lines) + "\n"


def matbench_command(args):
    try:
        if args.command == "matbench-prepare":
            result = prepare_template(
                args.cache_dir, args.dataset, args.out, download=args.download
            )
            print(
                f"Matbench {result['dataset']}: {result['n_samples']} official test records across five folds; metric {result['metric']}"
            )
            print(f"Prediction template: {result['template']}")
        else:
            result = evaluate_matbench(
                args.cache_dir,
                args.dataset,
                args.predictions,
                args.output_dir,
                prediction_column=args.prediction_column,
                release_policy_path=args.release_policy,
            )
            shared = result["artifact"]["shareable"]
            print(
                f"Matbench {shared['dataset']}: official unweighted {shared['metric']} fold mean {shared['fold_score_statistics']['mean']:.8g}"
            )
            print(
                f"Local result: {result['local_result']}; release: {result['release']['decision']}"
            )
        return 0
    except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError):
        print(
            "Matbench workflow rejected. Check the supported task, pinned cache, fold/ID coverage, probabilities, and fresh output paths."
        )
        return 2
