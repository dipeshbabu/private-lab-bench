"""A small, reproducible front door to the existing prediction-table runner."""

from __future__ import annotations

import csv
from dataclasses import asdict
import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from privatelabbench.eval.metrics import METRIC_DIRECTIONS
from privatelabbench.eval.uncertainty import BootstrapConfig
from privatelabbench.protocols import TASK_METRICS, apply_protocol, resolve_protocol
from privatelabbench.privacy.export import validate_policy
from privatelabbench.quality import validate_quality_policy


def _column(
    headers: Sequence[str],
    explicit: str | None,
    conventional: str,
    alternatives: set[str],
    flag: str,
) -> str:
    if explicit is not None:
        if explicit not in headers:
            raise ValueError(
                f"Column {explicit!r} is missing; select an existing column with {flag}"
            )
        return explicit
    if conventional not in headers:
        raise ValueError(
            f"Missing conventional {conventional!r} column; supply {flag} COLUMN"
        )
    if set(headers) & alternatives:
        raise ValueError(
            f"Several columns could serve as {conventional}; select one explicitly with {flag} COLUMN"
        )
    return conventional


def prediction_bindings(
    path: str | Path,
    *,
    target: str | None = None,
    prediction_column: str | None = None,
    prediction_columns: Sequence[str] | None = None,
    sample_id_column: str | None = None,
    task_type: str | None = None,
    class_labels: Sequence[str] | None = None,
    slices: Sequence[str] | None = None,
    metadata: Sequence[str] | None = None,
    baseline_column: str | None = None,
    frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    source = Path(path).resolve()
    with source.open(encoding="utf-8-sig", newline="") as handle:
        headers = next(csv.reader(handle), [])
    if (
        not headers
        or len(set(headers)) != len(headers)
        or any(not value.strip() for value in headers)
    ):
        raise ValueError("CSV header must contain nonempty, unique column names")
    selected_target = _column(
        headers, target, "target", {"label", "y_true"}, "--target"
    )
    sample_id = _column(
        headers, sample_id_column, "sample_id", set(), "--sample-id-column"
    )
    if prediction_column and prediction_columns:
        raise ValueError("Choose --prediction-column or ordered --prediction-columns")
    predictions = (
        list(prediction_columns)
        if prediction_columns
        else [
            _column(
                headers,
                prediction_column,
                "prediction",
                {"pred", "y_pred", "probability", "score"},
                "--prediction-column",
            )
        ]
    )
    if len(set(predictions)) != len(predictions) or any(
        column not in headers for column in predictions
    ):
        raise ValueError("Prediction columns must be unique existing columns")
    if (
        selected_target in predictions
        or sample_id in predictions
        or sample_id == selected_target
    ):
        raise ValueError(
            "Target, predictions, and stable sample IDs must use distinct columns"
        )
    for label, columns in (("slice", slices or ()), ("metadata", metadata or ())):
        if len(set(columns)) != len(columns) or any(
            column not in headers for column in columns
        ):
            raise ValueError(f"Every --{label} must select a unique existing column")
    if baseline_column and (
        baseline_column not in headers
        or baseline_column in {selected_target, sample_id}
    ):
        raise ValueError(
            "--baseline-column must select a distinct prediction column in this table"
        )
    labels = list(class_labels or ())
    if len(labels) != len(set(labels)) or any(not label.strip() for label in labels):
        raise ValueError("--class-labels must specify unique ordered labels")
    selected = (
        frame
        if frame is not None
        else pd.read_csv(
            source,
            usecols=list(
                dict.fromkeys(
                    [
                        selected_target,
                        sample_id,
                        *predictions,
                        *([baseline_column] if baseline_column else []),
                    ]
                )
            ),
        )
    )
    if selected[selected_target].isna().any():
        raise ValueError(
            "Target contains missing labels; resolve them before evaluation"
        )
    if selected[predictions].isna().any().any():
        raise ValueError(
            "Prediction columns contain missing values; resolve them before evaluation"
        )
    if baseline_column and selected[baseline_column].isna().any():
        raise ValueError(
            "Baseline predictions contain missing values; compare the same complete observations"
        )
    if (
        selected[sample_id].isna().any()
        or selected[sample_id].astype(str).str.strip().eq("").any()
    ):
        raise ValueError("Stable sample IDs contain missing/empty values")
    if selected[sample_id].duplicated().any():
        raise ValueError(
            "Stable sample IDs must be unique; remove accidental duplicates or provide correct observation IDs"
        )
    values = selected[selected_target]
    if task_type is None and len(predictions) > 1:
        if not labels:
            raise ValueError(
                "Multiclass probabilities need explicit ordered --class-labels matching --prediction-columns"
            )
        task_type = "multiclass"
    if task_type is None:
        numeric = pd.to_numeric(values, errors="coerce")
        if len(labels) == 2:
            task_type = "classification"
        elif (
            numeric.notna().all()
            and np.isfinite(numeric).all()
            and numeric.nunique() > 2
            and not np.equal(numeric, np.floor(numeric)).all()
        ):
            task_type = "regression"
        else:
            raise ValueError(
                "Task type is ambiguous; supply --task-type regression or --task-type classification (and ordered --class-labels for named classes)"
            )
    if task_type not in TASK_METRICS:
        raise ValueError(
            "Choose regression, classification, or multiclass with --task-type"
        )
    if task_type == "classification" and not labels:
        numeric = pd.to_numeric(values, errors="coerce")
        if numeric.notna().all() and set(numeric.unique()) == {0, 1}:
            # Preserve the table's numeric spelling while fixing 0 -> 1 order.
            labels = [str(values[numeric == index].iloc[0]) for index in (0, 1)]
        else:
            raise ValueError(
                "Binary probabilities need --class-labels NEGATIVE POSITIVE so their meaning is explicit"
            )
    if task_type == "regression" and labels:
        raise ValueError("Regression does not use --class-labels")
    if task_type == "classification" and len(labels) != 2:
        raise ValueError(
            "Binary classification requires exactly two ordered --class-labels"
        )
    if task_type == "multiclass" and (
        len(predictions) < 2 or len(labels) != len(predictions)
    ):
        raise ValueError(
            "Multiclass evaluation requires one ordered label per probability column"
        )
    result = {
        "path": str(source),
        "target_column": selected_target,
        "sample_id_column": sample_id,
        "require_sample_id": True,
        "task_type": task_type,
        "class_labels": labels,
    }
    result["prediction_columns" if len(predictions) > 1 else "prediction_column"] = (
        predictions if len(predictions) > 1 else predictions[0]
    )
    if slices is not None:
        result["slice_columns"] = list(slices)
    if metadata:
        result["metadata_columns"] = list(metadata)
    if baseline_column:
        result["baseline_prediction_column"] = baseline_column
    return result


def make_evaluation_config(
    path: str | Path,
    *,
    output_dir: str | Path,
    protocol: str | None = None,
    primary_metric: str | None = None,
    uncertainty: dict[str, Any] | None = None,
    min_slice_size: int | None = None,
    quality_policy: Any = None,
    release_policy: Any = None,
    **bindings: Any,
) -> dict[str, Any]:
    definition = resolve_protocol(protocol) if protocol else None
    if definition:
        rules = definition.as_dict()
        if (
            bindings.get("task_type") is not None
            and bindings["task_type"] != rules["task_type"]
        ):
            raise ValueError("--task-type conflicts with the selected protocol")
        if (
            bindings.get("class_labels") is not None
            and list(bindings["class_labels"]) != rules["input_schema"]["class_labels"]
        ):
            raise ValueError("--class-labels conflicts with the selected protocol")
        bindings["task_type"] = rules["task_type"]
        bindings["class_labels"] = rules["input_schema"]["class_labels"]
        if bindings.get("slices") is None:
            bindings["slices"] = rules["slices"]["required"]
        if primary_metric is not None and primary_metric != rules["primary_metric"]:
            raise ValueError(
                "--primary-metric conflicts with the protocol primary metric"
            )
        primary_metric = rules["primary_metric"]
    input_cfg = prediction_bindings(path, **bindings)
    if min_slice_size is not None and (
        type(min_slice_size) is not int or min_slice_size < 1
    ):
        raise ValueError("--min-slice-size must be a positive integer")
    task = input_cfg["task_type"]
    primary = (
        primary_metric
        or {
            "regression": "rmse",
            "classification": "auroc",
            "multiclass": "macro_auroc_ovr",
        }[task]
    )
    if primary not in TASK_METRICS[task]:
        raise ValueError("--primary-metric is incompatible with the task type")
    output = Path(output_dir).resolve()
    cfg = {
        "project": "local-evaluation",
        "task": rules["task"] if definition else "predictions",
        "input": input_cfg,
        "evaluation": {"primary_metric": primary},
        "report": {
            "json": str(output / "evaluation.json"),
            "markdown": str(output / "evaluation.md"),
            "manifest": str(output / "evaluation_manifest.json"),
        },
        "audit": {"path": str(output / "audit.jsonl")},
    }
    settings = uncertainty or {}
    if not definition:
        settings = {**asdict(BootstrapConfig(enabled=True)), **settings}
        BootstrapConfig(**settings).validate()
        input_cfg["min_slice_size"] = (
            min_slice_size if min_slice_size is not None else 5
        )
    elif min_slice_size is not None:
        input_cfg["min_slice_size"] = min_slice_size
    if settings:
        cfg["uncertainty"] = settings
    if quality_policy is not None:
        cfg["quality_gate"] = validate_quality_policy(quality_policy)
    if release_policy is not None:
        cfg["release"] = validate_policy(release_policy)
    if definition:
        # Validate all bound settings now, but keep the reusable reference in YAML.
        cfg["protocol"] = (
            definition.ref
            if protocol.startswith("plb://")
            else str(Path(protocol).resolve())
        )
        cfg["protocol_sha256"] = definition.sha256
        apply_protocol(cfg, definition)
    return cfg


def evaluation_summary(
    summary: dict[str, Any],
    report: dict[str, Any],
    primary: str,
    release: dict[str, Any],
    receipt: Path,
) -> str:
    result = report["result"]
    metric = result.get("reported_metrics", {}).get(primary)
    number = (
        f"{metric:.6g}"
        if isinstance(metric, (int, float)) and math.isfinite(metric)
        else "undefined"
    )
    lines = [
        "PrivateLabBench",
        f"Task                 {summary['task_type']}",
        f"Samples              {summary['n_samples']}",
        f"{primary.upper():<21}{number}",
    ]
    if summary.get("evaluation_protocol"):
        protocol = summary["evaluation_protocol"]
        lines.insert(2, f"Protocol             {protocol['id']}@{protocol['version']}")
    if summary["task_type"] == "classification":
        lines.insert(2, f"Positive class       {result['class_labels'][-1]}")
    mode = report.get("privacy", {}).get("mode", "none")
    uncertainty = result.get("uncertainty", {})
    interval = uncertainty.get("metrics", {}).get(primary, {})
    if mode == "none" and interval.get("status") == "evaluated":
        lines.append(
            f"{uncertainty['confidence_level']:.0%} CI               [{interval['lower']:.6g}, {interval['upper']:.6g}]"
        )
    else:
        lines.append(
            f"Uncertainty          {interval.get('status', uncertainty.get('status', 'unavailable')) if mode == 'none' else 'withheld: metric basis differs'}"
        )
    baseline = result.get("baseline_metrics", {}).get(primary)
    if (
        mode == "none"
        and isinstance(baseline, (int, float))
        and math.isfinite(baseline)
        and isinstance(metric, (int, float))
        and math.isfinite(metric)
    ):
        improvement = (
            baseline - metric
            if METRIC_DIRECTIONS[primary] == "lower_is_better"
            else metric - baseline
        )
        relative = (
            f" ({100 * improvement / abs(baseline):+.1f}%)"
            if baseline
            else " (zero baseline; relative change undefined)"
        )
        lines.append(f"Baseline improvement {improvement:+.6g}{relative}")
    candidates = [
        (entry["metrics"][primary], column, label)
        for column, groups in result.get("slice_metrics", {}).items()
        for label, entry in groups.items()
        if entry.get("status") == "evaluated"
        and isinstance(entry.get("metrics", {}).get(primary), (int, float))
        and math.isfinite(entry["metrics"][primary])
    ]
    if candidates:
        value, column, label = (
            max if METRIC_DIRECTIONS[primary] == "lower_is_better" else min
        )(candidates)
        lines.append(f"Worst slice          {column}={label} ({primary} {value:.6g})")
    elif result.get("slice_metrics"):
        lines.append(
            "Slices               insufficient size or undefined metric; inspect local report"
        )
    if "quality_gate" in summary:
        lines.append(f"Quality gate         {summary['quality_gate']['status']}")
    if summary.get("degradation_summary"):
        changes = summary["degradation_summary"]
        overall = changes["overall"][primary]
        lines.append(
            f"Cohort change        {overall['status']}; degradation {overall['degradation']}; relative {overall['relative_degradation']}"
        )
        lines.append(f"Delta uncertainty    {overall['interval']['status']}")
        if overall["interval"]["status"] == "evaluated":
            interval = overall["interval"]
            lines.append(
                f"Delta CI             [{interval['lower']:.6g}, {interval['upper']:.6g}]"
            )
        if changes["ranked_slices"]:
            worst = changes["ranked_slices"][0]
            lines.append(
                f"Largest degradation  {worst['column']}={worst['value']} ({primary} {worst['degradation']:+.6g})"
            )
    decision = release.get("decision", "needs_review")
    reason = (
        "shareable"
        if decision == "allow"
        else (
            "local only; release disabled"
            if "release_disabled" in release.get("reason_codes", [])
            else (
                "local only; no release policy"
                if "missing_policy" in release.get("reason_codes", [])
                else f"{decision}; inspect local release audit"
            )
        )
    )
    lines += [
        f"Privacy              {mode}; no formal DP guarantee",
        f"Release              {reason}",
        f"Receipt              {receipt}",
    ]
    return "\n".join(lines)
