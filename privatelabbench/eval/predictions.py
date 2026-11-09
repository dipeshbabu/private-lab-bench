from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from privatelabbench.eval.metrics import (
    classification_metrics,
    multiclass_metrics,
    regression_metrics,
)
from privatelabbench.eval.slices import iter_slice_groups
from privatelabbench.eval.uncertainty import BootstrapConfig, bootstrap_metric_intervals
from privatelabbench.privacy.attacks import membership_inference_risk
from privatelabbench.tasks.molecules import infer_task_type

SUPPORTED_PREDICTION_TASK_TYPES = {"regression", "classification", "multiclass"}


@dataclass(frozen=True)
class PredictionTableSchema:
    sample_id_column: str | None
    sample_id_status: str
    target_column: str
    prediction_columns: tuple[str, ...]
    metadata_columns: tuple[str, ...]
    slice_columns: tuple[str, ...]
    split_column: str | None
    class_labels: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "prediction-table/v1",
            "sample_id_column": self.sample_id_column,
            "sample_id_status": self.sample_id_status,
            "target_column": self.target_column,
            "prediction_columns": list(self.prediction_columns),
            "metadata_columns": list(self.metadata_columns),
            "slice_columns": list(self.slice_columns),
            "split_column": self.split_column,
            "class_labels": list(self.class_labels),
        }


@dataclass(frozen=True)
class PredictionEvaluation:
    dataset_path: str
    target_column: str
    prediction_column: str | None
    prediction_columns: tuple[str, ...]
    task_type: str
    n_samples: int
    metrics: dict[str, float]
    prediction_summary: dict[str, float]
    schema: PredictionTableSchema
    slice_metrics: dict[str, dict[str, dict[str, object]]]
    sample_id_column: str | None = None
    sample_id_status: str = "missing"
    split_column: str | None = None
    class_labels: tuple[str, ...] = ()
    privacy_risk: dict[str, float | str] | None = None
    uncertainty: dict[str, object] | None = None


def _summary(values: np.ndarray, prefix: str) -> dict[str, float]:
    return {
        f"{prefix}_mean": float(np.mean(values)),
        f"{prefix}_std": float(np.std(values)),
        f"{prefix}_min": float(np.min(values)),
        f"{prefix}_max": float(np.max(values)),
    }


def validate_evaluation_group(frame: pd.DataFrame, group: Any) -> None:
    if group is None:
        return
    if (
        not isinstance(group, dict)
        or set(group) != {"column", "max_groups"}
        or not isinstance(group["column"], str)
        or type(group["max_groups"]) is not int
        or group["max_groups"] != 1
    ):
        raise ValueError("Unsupported protocol evaluation-group declaration")
    column = group["column"]
    if (
        column not in frame
        or frame.empty
        or frame[column].isna().any()
        or frame[column].nunique(dropna=False) != 1
    ):
        raise ValueError(
            "The protocol requires exactly one nonmissing evaluation group; evaluate assays separately"
        )


def _normalize_split_value(value: Any) -> str:
    normalized = str(value).strip().lower()
    if normalized in {"train", "training", "member", "members", "in", "1", "true"}:
        return "train"
    if normalized in {
        "test",
        "holdout",
        "validation",
        "val",
        "nonmember",
        "nonmembers",
        "out",
        "0",
        "false",
    }:
        return "test"
    raise ValueError(
        "split_column values must identify train/member rows and test/nonmember rows. "
        f"Unsupported value: {value!r}"
    )


def _normalize_string_list(
    value: Sequence[str] | None, *, label: str
) -> tuple[str, ...]:
    if value is None:
        return ()
    out = tuple(str(item).strip() for item in value)
    if any(not item for item in out):
        raise ValueError(f"{label} cannot contain empty column names")
    if len(out) != len(set(out)):
        raise ValueError(f"{label} cannot contain duplicate values")
    return out


def _resolve_prediction_columns(
    *,
    prediction_column: str | None,
    prediction_columns: Sequence[str] | None,
) -> tuple[str, ...]:
    columns = _normalize_string_list(prediction_columns, label="prediction_columns")
    single = str(prediction_column).strip() if prediction_column is not None else ""
    if single and columns:
        raise ValueError(
            "Use either prediction_column or prediction_columns, not both."
        )
    if single:
        return (single,)
    if columns:
        return columns
    raise ValueError(
        "A prediction table requires prediction_column or prediction_columns."
    )


def validate_prediction_roles(*, target, prediction_columns, sample_id_column):
    columns = [target, *prediction_columns]
    if sample_id_column:
        columns.append(sample_id_column)
    if len(set(columns)) != len(columns):
        raise ValueError(
            "Target, predictions, and stable sample IDs must use distinct columns"
        )


def _infer_or_validate_task_type(
    *,
    task_type: str | None,
    target_values: np.ndarray,
    prediction_columns: tuple[str, ...],
) -> str:
    if task_type:
        normalized = str(task_type).strip().lower()
    elif len(prediction_columns) > 1:
        normalized = "multiclass"
    else:
        try:
            normalized = infer_task_type(target_values.astype(float))
        except (TypeError, ValueError):
            unique = pd.unique(target_values)
            normalized = "classification" if len(unique) == 2 else "multiclass"
    if normalized not in SUPPORTED_PREDICTION_TASK_TYPES:
        raise ValueError(
            "task_type must be one of: regression, classification, multiclass"
        )
    if normalized == "multiclass" and len(prediction_columns) < 2:
        raise ValueError(
            "multiclass evaluation requires prediction_columns with at least two probability columns"
        )
    if normalized != "multiclass" and len(prediction_columns) != 1:
        raise ValueError(
            f"{normalized} evaluation requires exactly one prediction column"
        )
    return normalized


def _validate_sample_ids(
    df: pd.DataFrame,
    *,
    sample_id_column: str | None,
    require_sample_id: bool,
) -> tuple[str | None, str]:
    if not sample_id_column:
        if require_sample_id:
            raise ValueError(
                "sample_id_column is required for reproducible prediction-table evaluation"
            )
        return None, "not_configured"
    if sample_id_column not in df.columns:
        if require_sample_id:
            raise ValueError(
                f"Missing sample id column '{sample_id_column}'. "
                "Add stable sample IDs or set require_sample_id: false explicitly."
            )
        return sample_id_column, "missing"
    values = df[sample_id_column]
    if values.isna().any() or values.astype(str).str.strip().eq("").any():
        raise ValueError(
            f"sample id column '{sample_id_column}' contains missing/empty values"
        )
    if values.duplicated().any():
        duplicates = values[values.duplicated()].astype(str).head(3).tolist()
        raise ValueError(
            f"sample id column '{sample_id_column}' must be unique; duplicate example(s): {', '.join(duplicates)}"
        )
    return sample_id_column, "present"


def _encode_binary_targets(
    values: np.ndarray,
    *,
    class_labels: Sequence[str] | None = None,
) -> tuple[np.ndarray, tuple[str, ...]]:
    # A single score always denotes probability of the second ordered class.
    # Row order must never change the meaning of that score.
    labels = (
        tuple(str(label) for label in class_labels)
        if class_labels
        else tuple(sorted({str(value) for value in values}))
    )
    if len(labels) != 2:
        raise ValueError(
            f"binary classification requires exactly two class labels; found {len(labels)}"
        )
    if len(labels) != len(set(labels)):
        raise ValueError("class_labels must be unique")
    mapping = {label: index for index, label in enumerate(labels)}
    unknown = sorted({str(value) for value in values if str(value) not in mapping})
    if unknown:
        raise ValueError(
            f"Target contains class label(s) not present in class_labels: {', '.join(unknown)}"
        )
    encoded = np.array([mapping[str(value)] for value in values], dtype=int)
    return encoded, labels


def _encode_multiclass_targets(
    values: np.ndarray,
    *,
    class_labels: Sequence[str] | None,
    n_prediction_columns: int,
) -> tuple[np.ndarray, tuple[str, ...]]:
    configured = tuple(str(label) for label in class_labels) if class_labels else ()
    if not configured:
        raise ValueError(
            "class_labels is required for multiclass evaluation so probability-column order is explicit"
        )
    labels = configured
    if len(labels) != n_prediction_columns:
        raise ValueError(
            "class_labels must contain exactly one label per multiclass prediction column "
            f"({n_prediction_columns} columns, {len(labels)} labels)"
        )
    if len(labels) != len(set(labels)):
        raise ValueError("class_labels must be unique")
    mapping = {label: index for index, label in enumerate(labels)}
    unknown = sorted({str(value) for value in values if str(value) not in mapping})
    if unknown:
        raise ValueError(
            f"Target contains class label(s) not present in class_labels: {', '.join(unknown)}"
        )
    encoded = np.array([mapping[str(value)] for value in values], dtype=int)
    return encoded, labels


def _validate_multiclass_probabilities(probabilities: np.ndarray) -> None:
    if not np.all(np.isfinite(probabilities)):
        raise ValueError("multiclass prediction columns contain non-finite values")
    if np.any(probabilities < 0.0) or np.any(probabilities > 1.0):
        raise ValueError(
            "multiclass prediction columns must contain probabilities between 0 and 1"
        )
    row_sums = probabilities.sum(axis=1)
    if not np.allclose(row_sums, 1.0, atol=1e-4):
        bad = float(row_sums[np.argmax(np.abs(row_sums - 1.0))])
        raise ValueError(
            "multiclass probability rows must sum to 1.0 "
            f"(found row sum {bad:.6f}); normalize scores before evaluation"
        )


def _metrics_for_task(
    *,
    task_type: str,
    y_true: np.ndarray,
    prediction_values: np.ndarray,
    metric_names=None,
) -> dict[str, float]:
    if task_type == "regression":
        return regression_metrics(
            y_true.astype(float),
            prediction_values.astype(float),
            metric_names=metric_names,
        )
    if task_type == "classification":
        return classification_metrics(
            y_true.astype(int),
            prediction_values.astype(float),
            metric_names=metric_names,
        )
    return multiclass_metrics(
        y_true.astype(int),
        prediction_values.astype(float),
        labels=list(range(prediction_values.shape[1])),
        metric_names=metric_names,
    )


def _slice_metrics(
    df: pd.DataFrame,
    *,
    slice_columns: tuple[str, ...],
    min_slice_size: int,
    task_type: str,
    target_values: np.ndarray,
    prediction_values: np.ndarray,
    uncertainty_config: BootstrapConfig | None = None,
    sampling_design: Any = None,
    metric_names=None,
) -> dict[str, dict[str, dict[str, object]]]:
    if min_slice_size < 1:
        raise ValueError("min_slice_size must be at least 1")
    out: dict[str, dict[str, dict[str, object]]] = {}
    slice_counter = 0
    for column in slice_columns:
        column_results: dict[str, dict[str, object]] = {}
        for key, index_array in iter_slice_groups(df, column):
            entry: dict[str, object] = {"n": int(len(index_array))}
            if sampling_design:
                from privatelabbench.eval.sampling import plan_sampling

                entry["n_independent_units"] = plan_sampling(
                    df.iloc[index_array], sampling_design
                ).n_units
            if len(index_array) < min_slice_size:
                entry["status"] = "skipped_min_slice_size"
            else:
                entry["status"] = "evaluated"
                entry["metrics"] = _metrics_for_task(
                    task_type=task_type,
                    y_true=target_values[index_array],
                    prediction_values=prediction_values[index_array],
                    metric_names=metric_names,
                )
                if (
                    uncertainty_config
                    and uncertainty_config.enabled
                    and uncertainty_config.include_slices
                ):
                    slice_counter += 1
                    entry["uncertainty"] = bootstrap_metric_intervals(
                        task_type=task_type,
                        y_true=target_values[index_array],
                        predictions=prediction_values[index_array],
                        config=uncertainty_config.for_slice(seed_offset=slice_counter),
                        sampling_design=sampling_design,
                        sampling_metadata=df.iloc[index_array].reset_index(drop=True),
                        metric_names=metric_names,
                    )
            column_results[key] = entry
        out[column] = column_results
    return out


def evaluate_prediction_csv(
    path: str,
    *,
    target: str,
    prediction_column: str | None = None,
    prediction_columns: Sequence[str] | None = None,
    task_type: str | None = None,
    sample_id_column: str | None = "sample_id",
    require_sample_id: bool = False,
    metadata_columns: Sequence[str] | None = None,
    slice_columns: Sequence[str] | None = None,
    min_slice_size: int = 2,
    class_labels: Sequence[str] | None = None,
    split_column: str | None = None,
    uncertainty_config: BootstrapConfig | None = None,
    sampling_design: Any = None,
    metric_names=None,
    evaluation_group=None,
) -> PredictionEvaluation:
    from privatelabbench.eval.sampling import sampling_design as parse_design

    design = parse_design(sampling_design)
    return evaluate_prediction_table(
        pd.read_csv(
            path,
            dtype={
                **({sample_id_column: "string"} if sample_id_column else {}),
                **({target: "string"} if class_labels else {}),
                **({evaluation_group["column"]: "string"} if evaluation_group else {}),
                **(
                    {column: "string" for column in design.metadata_columns}
                    if design
                    else {}
                ),
            },
        ),
        dataset_path=str(path),
        target=target,
        prediction_column=prediction_column,
        prediction_columns=prediction_columns,
        task_type=task_type,
        sample_id_column=sample_id_column,
        require_sample_id=require_sample_id,
        metadata_columns=metadata_columns,
        slice_columns=slice_columns,
        min_slice_size=min_slice_size,
        class_labels=class_labels,
        split_column=split_column,
        uncertainty_config=uncertainty_config,
        sampling_design=design,
        metric_names=metric_names,
        evaluation_group=evaluation_group,
    )


def evaluate_prediction_table(
    df: pd.DataFrame,
    *,
    dataset_path: str = "in-memory",
    target: str,
    prediction_column: str | None = None,
    prediction_columns: Sequence[str] | None = None,
    task_type: str | None = None,
    sample_id_column: str | None = "sample_id",
    require_sample_id: bool = False,
    metadata_columns: Sequence[str] | None = None,
    slice_columns: Sequence[str] | None = None,
    min_slice_size: int = 2,
    class_labels: Sequence[str] | None = None,
    split_column: str | None = None,
    uncertainty_config: BootstrapConfig | None = None,
    sampling_design: Any = None,
    metric_names=None,
    evaluation_group=None,
) -> PredictionEvaluation:
    path = dataset_path
    if not isinstance(df, pd.DataFrame) or df.columns.duplicated().any():
        raise ValueError(
            "Prediction table must be a DataFrame with unique column names"
        )
    validate_evaluation_group(df, evaluation_group)
    from privatelabbench.eval.sampling import sampling_design as parse_design

    design = parse_design(sampling_design)
    prediction_cols = _resolve_prediction_columns(
        prediction_column=prediction_column,
        prediction_columns=prediction_columns,
    )
    validate_prediction_roles(
        target=target,
        prediction_columns=prediction_cols,
        sample_id_column=sample_id_column,
    )
    configured_metadata = _normalize_string_list(
        metadata_columns, label="metadata_columns"
    )
    configured_slices = _normalize_string_list(slice_columns, label="slice_columns")
    if design:
        configured_slices = tuple(
            dict.fromkeys(
                [
                    *configured_slices,
                    *[column for column, value in design.critical_slices],
                ]
            )
        )

    required = {target, *prediction_cols, *configured_metadata, *configured_slices}
    if split_column:
        required.add(split_column)
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            "Prediction table is missing required column(s): "
            f"{', '.join(sorted(missing))}. Available columns: {', '.join(map(str, df.columns))}"
        )

    resolved_sample_id_column, sample_id_status = _validate_sample_ids(
        df,
        sample_id_column=sample_id_column,
        require_sample_id=require_sample_id,
    )

    required_values = [target, *prediction_cols]
    if split_column:
        required_values.append(split_column)
    if df[required_values].isna().any().any():
        raise ValueError(
            "Prediction evaluation requires complete targets/predictions and declared "
            "split values; repair missing values or apply explicit predeclared "
            "exclusions/eligibility before evaluation. Rows are never implicitly dropped."
        )
    if df.empty:
        raise ValueError("Prediction table must contain at least one evaluation row.")
    df = df.reset_index(drop=True)

    raw_targets = df[target].to_numpy()
    resolved_task_type = _infer_or_validate_task_type(
        task_type=task_type,
        target_values=raw_targets,
        prediction_columns=prediction_cols,
    )

    labels: tuple[str, ...] = ()
    if resolved_task_type == "regression":
        try:
            y_true = df[target].astype(float).to_numpy()
            prediction_values = df[prediction_cols[0]].astype(float).to_numpy()
        except ValueError as exc:
            raise ValueError(
                "Regression target and prediction columns must be numeric."
            ) from exc
        metrics = regression_metrics(
            y_true, prediction_values, metric_names=metric_names
        )
        prediction_summary = {
            **_summary(y_true, "target"),
            **_summary(prediction_values, "prediction"),
            **(
                {"mean_absolute_prediction_error": metrics["mae"]}
                if "mae" in metrics
                else {}
            ),
        }
    elif resolved_task_type == "classification":
        y_true, labels = _encode_binary_targets(raw_targets, class_labels=class_labels)
        try:
            prediction_values = df[prediction_cols[0]].astype(float).to_numpy()
        except ValueError as exc:
            raise ValueError(
                "Binary classification prediction column must contain numeric probabilities."
            ) from exc
        if np.any(prediction_values < 0.0) or np.any(prediction_values > 1.0):
            raise ValueError(
                "Binary classification prediction probabilities must be between 0 and 1."
            )
        metrics = classification_metrics(
            y_true, prediction_values, metric_names=metric_names
        )
        prediction_summary = {
            **_summary(prediction_values, "prediction"),
            "positive_rate": float(np.mean(y_true)),
        }
    else:
        try:
            probabilities = df[list(prediction_cols)].astype(float).to_numpy()
        except ValueError as exc:
            raise ValueError(
                "Multiclass prediction columns must contain numeric probabilities."
            ) from exc
        _validate_multiclass_probabilities(probabilities)
        y_true, labels = _encode_multiclass_targets(
            raw_targets,
            class_labels=class_labels,
            n_prediction_columns=len(prediction_cols),
        )
        prediction_values = probabilities
        metrics = multiclass_metrics(
            y_true,
            probabilities,
            labels=list(range(len(labels))),
            metric_names=metric_names,
        )
        confidence = probabilities.max(axis=1)
        safe_probabilities = np.clip(probabilities, 1e-12, 1.0)
        entropy = -np.sum(probabilities * np.log(safe_probabilities), axis=1)
        prediction_summary = {
            "mean_confidence": float(np.mean(confidence)),
            "min_confidence": float(np.min(confidence)),
            "max_confidence": float(np.max(confidence)),
            "mean_entropy": float(np.mean(entropy)),
        }

    resolved_uncertainty = uncertainty_config or BootstrapConfig(enabled=False)
    uncertainty = (
        bootstrap_metric_intervals(
            task_type=resolved_task_type,
            y_true=y_true,
            predictions=prediction_values,
            config=resolved_uncertainty,
            sampling_design=design,
            sampling_metadata=df,
            metric_names=metric_names,
        )
        if resolved_uncertainty.enabled or design
        else {}
    )

    inferred_metadata = tuple(
        str(column)
        for column in df.columns
        if column not in {target, *prediction_cols}
        and column != resolved_sample_id_column
        and column != split_column
    )
    metadata = inferred_metadata

    slices = _slice_metrics(
        df,
        slice_columns=configured_slices,
        min_slice_size=min_slice_size,
        task_type=resolved_task_type,
        target_values=y_true,
        prediction_values=prediction_values,
        uncertainty_config=resolved_uncertainty,
        sampling_design=design,
        metric_names=metric_names,
    )

    privacy_risk = None
    if split_column:
        if resolved_task_type == "multiclass":
            raise ValueError(
                "split_column membership-inference auditing currently supports regression and binary classification only"
            )
        split = df[split_column].map(_normalize_split_value).to_numpy()
        train_mask = split == "train"
        test_mask = split == "test"
        privacy_risk = membership_inference_risk(
            train_y=y_true[train_mask],
            train_score=prediction_values[train_mask],
            test_y=y_true[test_mask],
            test_score=prediction_values[test_mask],
            task_type=resolved_task_type,
        )
        privacy_risk["split_column"] = split_column

    schema = PredictionTableSchema(
        sample_id_column=resolved_sample_id_column,
        sample_id_status=sample_id_status,
        target_column=target,
        prediction_columns=prediction_cols,
        metadata_columns=tuple(metadata),
        slice_columns=configured_slices,
        split_column=split_column,
        class_labels=labels,
    )

    return PredictionEvaluation(
        dataset_path=path,
        target_column=target,
        prediction_column=prediction_cols[0] if len(prediction_cols) == 1 else None,
        prediction_columns=prediction_cols,
        task_type=resolved_task_type,
        n_samples=int(len(df)),
        metrics=metrics,
        prediction_summary=prediction_summary,
        schema=schema,
        slice_metrics=slices,
        sample_id_column=resolved_sample_id_column,
        sample_id_status=sample_id_status,
        split_column=split_column,
        class_labels=labels,
        privacy_risk=privacy_risk,
        uncertainty=uncertainty,
    )
