from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from privatelabbench.config import RunnerConfig, load_config, required, section
from privatelabbench.core.registry import discover_entrypoint_tasks, get_task
from privatelabbench.eval.predictions import evaluate_prediction_csv
from privatelabbench.eval.uncertainty import BootstrapConfig
from privatelabbench.privacy.dp import PrivacyConfig
from privatelabbench.privacy.policy import PrivacyRiskPolicy
from privatelabbench.privacy.release import AggregateReleasePolicy
from privatelabbench.runner import ensure_builtin_tasks_registered


@dataclass(frozen=True)
class ConfigValidationResult:
    config_path: str
    project: str | None = None
    workflow: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


def _resolve_path(path: str | os.PathLike[str], *, config_path: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    repo_relative = Path.cwd() / candidate
    if repo_relative.exists():
        return repo_relative
    return config_path.parent / candidate


def _resolve_output_path(path: str | os.PathLike[str]) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return Path.cwd() / candidate


def _csv_columns(path: Path) -> set[str]:
    try:
        return set(pd.read_csv(path, nrows=0).columns)
    except Exception as exc:
        raise ValueError(f"Could not read CSV header from {path}: {exc}") from exc


def _require_columns(path: Path, columns: set[str], required_columns: set[str], errors: list[str]) -> None:
    missing = required_columns - columns
    if missing:
        errors.append(f"{path} is missing required column(s): {', '.join(sorted(missing))}")


def _validate_input_file(path_value: Any, *, config_path: Path, errors: list[str]) -> Path | None:
    if not path_value:
        return None
    path = _resolve_path(str(path_value), config_path=config_path)
    if not path.exists():
        errors.append(f"Input file does not exist: {path}")
        return None
    if not path.is_file():
        errors.append(f"Input path is not a file: {path}")
        return None
    return path


def _validate_output_path(path_value: Any, *, label: str, errors: list[str], warnings: list[str]) -> None:
    if not path_value:
        return
    path = _resolve_output_path(str(path_value))
    parent = path.parent
    if parent.exists():
        if not parent.is_dir():
            errors.append(f"{label} parent is not a directory: {parent}")
        elif not os.access(parent, os.W_OK):
            errors.append(f"{label} parent is not writable: {parent}")
        return
    existing = parent
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    if not existing.exists():
        errors.append(f"{label} has no existing writable ancestor: {parent}")
    elif not os.access(existing, os.W_OK):
        errors.append(f"{label} ancestor is not writable: {existing}")
    else:
        warnings.append(f"{label} parent will be created at run time: {parent}")


def _validate_task_type(value: Any, errors: list[str]) -> None:
    if value not in (None, "", "regression", "classification", "multiclass"):
        errors.append("input.task_type must be 'regression', 'classification', or 'multiclass' when provided.")


def _string_list(value: Any, *, key: str, errors: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"{key} must be a YAML list.")
        return []
    out = [str(item).strip() for item in value]
    if any(not item for item in out):
        errors.append(f"{key} cannot contain empty values.")
    if len(out) != len(set(out)):
        errors.append(f"{key} cannot contain duplicate values.")
    return out


def _validate_privacy(config: RunnerConfig, errors: list[str]) -> None:
    privacy = section(config, "privacy")
    try:
        PrivacyConfig(
            mode=str(privacy.get("mode", "none")),
            epsilon=float(privacy.get("epsilon", 8.0)),
            sensitivity=float(privacy.get("sensitivity", 1.0)),
            seed=int(privacy.get("seed", 13)),
        ).validate()
        risk_policy = privacy.get("risk_policy")
        if risk_policy is not None and not isinstance(risk_policy, dict):
            raise ValueError("privacy.risk_policy must be a mapping.")
        PrivacyRiskPolicy.from_config(risk_policy)
        aggregate_policy = privacy.get("aggregate_policy")
        if aggregate_policy is not None and not isinstance(aggregate_policy, dict):
            raise ValueError("privacy.aggregate_policy must be a mapping.")
        aggregate = AggregateReleasePolicy.from_config(aggregate_policy)
        if aggregate.min_clients < 1:
            raise ValueError("privacy.aggregate_policy.min_clients must be at least 1.")
    except Exception as exc:
        errors.append(f"Invalid privacy config: {exc}")


def _validate_uncertainty(config: RunnerConfig, errors: list[str]) -> None:
    uncertainty = section(config, "uncertainty")
    try:
        BootstrapConfig(
            enabled=bool(uncertainty.get("enabled", False)),
            method=str(uncertainty.get("method", "percentile_bootstrap")),
            confidence_level=float(uncertainty.get("confidence_level", 0.95)),
            resamples=int(uncertainty.get("resamples", 1000)),
            seed=int(uncertainty.get("seed", 13)),
            min_samples=int(uncertainty.get("min_samples", 20)),
            include_slices=bool(uncertainty.get("include_slices", False)),
        ).validate()
    except Exception as exc:
        errors.append(f"Invalid uncertainty config: {exc}")


def _validate_reports(config: RunnerConfig, *, errors: list[str], warnings: list[str]) -> None:
    report = section(config, "report")
    defaults = {
        "markdown": f"reports/{config.project}_{config.workflow}_eval.md",
        "json": f"reports/{config.project}_{config.workflow}_eval.json",
        "manifest": f"reports/{config.project}_{config.workflow}_manifest.json",
    }
    for key, default in defaults.items():
        _validate_output_path(report.get(key, default), label=f"report.{key}", errors=errors, warnings=warnings)
    audit = section(config, "audit")
    _validate_output_path(
        audit.get("path", f"reports/{config.project}_audit.jsonl"),
        label="audit.path",
        errors=errors,
        warnings=warnings,
    )


def _validate_predictions(
    config: RunnerConfig,
    *,
    config_path: Path,
    errors: list[str],
    warnings: list[str],
) -> None:
    input_cfg = section(config, "input")
    path_value = required(input_cfg, "path", section_name="input")
    target = str(required(input_cfg, "target_column", section_name="input"))
    prediction_column = input_cfg.get("prediction_column")
    prediction_columns = _string_list(input_cfg.get("prediction_columns"), key="input.prediction_columns", errors=errors)
    if prediction_column is None and not prediction_columns:
        errors.append("input.prediction_column or input.prediction_columns is required.")
    if prediction_column is not None and prediction_columns:
        errors.append("Use either input.prediction_column or input.prediction_columns, not both.")

    metadata_columns = _string_list(input_cfg.get("metadata_columns"), key="input.metadata_columns", errors=errors)
    slice_columns = _string_list(input_cfg.get("slice_columns"), key="input.slice_columns", errors=errors)
    class_labels = _string_list(input_cfg.get("class_labels"), key="input.class_labels", errors=errors)
    split_column = input_cfg.get("split_column")
    baseline_prediction_column = input_cfg.get("baseline_prediction_column")
    sample_id_value = input_cfg.get("sample_id_column", "sample_id")
    sample_id_column = str(sample_id_value) if sample_id_value not in (None, "") else None
    require_sample_id = bool(input_cfg.get("require_sample_id", False))
    min_slice_size = int(input_cfg.get("min_slice_size", 2))
    _validate_task_type(input_cfg.get("task_type"), errors)

    if min_slice_size < 1:
        errors.append("input.min_slice_size must be at least 1.")

    path = _validate_input_file(path_value, config_path=config_path, errors=errors)
    if path is None:
        return

    columns = _csv_columns(path)
    required_columns = {target, *prediction_columns, *metadata_columns, *slice_columns}
    if prediction_column is not None:
        required_columns.add(str(prediction_column))
    if baseline_prediction_column:
        required_columns.add(str(baseline_prediction_column))
    if split_column:
        required_columns.add(str(split_column))
    _require_columns(path, columns, required_columns, errors)

    if sample_id_column and sample_id_column not in columns:
        message = (
            f"Prediction table has no '{sample_id_column}' column. "
            "Stable sample IDs are strongly recommended for reproducibility."
        )
        if require_sample_id:
            errors.append(message)
        else:
            warnings.append(message)

    task_type = input_cfg.get("task_type")
    if task_type == "multiclass" and len(prediction_columns) < 2:
        errors.append("multiclass evaluation requires input.prediction_columns with at least two columns.")
    if class_labels and prediction_columns and len(class_labels) != len(prediction_columns):
        errors.append("input.class_labels must contain exactly one label per input.prediction_columns entry.")

    if errors:
        return

    try:
        result = evaluate_prediction_csv(
            str(path),
            target=target,
            prediction_column=str(prediction_column) if prediction_column is not None else None,
            prediction_columns=prediction_columns or None,
            task_type=str(task_type) if task_type else None,
            sample_id_column=sample_id_column,
            require_sample_id=require_sample_id,
            metadata_columns=metadata_columns or None,
            slice_columns=slice_columns or None,
            min_slice_size=min_slice_size,
            class_labels=class_labels or None,
            split_column=str(split_column) if split_column else None,
        )
        if result.sample_id_status != "present" and not require_sample_id:
            warnings.append(
                "Run can proceed without stable sample IDs, but reproducibility across reordered prediction tables is weaker."
            )
    except Exception as exc:
        errors.append(f"Invalid prediction table: {exc}")


def _validate_molecules(config: RunnerConfig, *, config_path: Path, errors: list[str]) -> None:
    input_cfg = section(config, "input")
    path_value = required(input_cfg, "path", section_name="input")
    target = str(required(input_cfg, "target_column", section_name="input"))
    smiles_column = str(input_cfg.get("smiles_column", "smiles"))
    _validate_task_type(input_cfg.get("task_type"), errors)
    path = _validate_input_file(path_value, config_path=config_path, errors=errors)
    if path is None:
        return
    _require_columns(path, _csv_columns(path), {target, smiles_column}, errors)


def _validate_federated(config: RunnerConfig, *, config_path: Path, errors: list[str]) -> None:
    input_cfg = section(config, "input")
    client_dir_value = required(input_cfg, "client_dir", section_name="input")
    target = str(required(input_cfg, "target_column", section_name="input"))
    smiles_column = str(input_cfg.get("smiles_column", "smiles"))
    _validate_task_type(input_cfg.get("task_type"), errors)
    client_dir = _resolve_path(str(client_dir_value), config_path=config_path)
    if not client_dir.exists():
        errors.append(f"input.client_dir does not exist: {client_dir}")
        return
    if not client_dir.is_dir():
        errors.append(f"input.client_dir is not a directory: {client_dir}")
        return
    csvs = sorted(client_dir.glob("*.csv"))
    if not csvs:
        errors.append(f"input.client_dir contains no CSV files: {client_dir}")
        return
    for csv_path in csvs:
        _require_columns(csv_path, _csv_columns(csv_path), {target, smiles_column}, errors)


def validate_config(config_path: str) -> ConfigValidationResult:
    path = Path(config_path)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        config = load_config(config_path)
        project = config.project
        workflow = config.workflow
        ensure_builtin_tasks_registered()
        discover_entrypoint_tasks()
        get_task(config.task_id)

        if config.task_id in {"predictions", "tabular"}:
            _validate_predictions(config, config_path=path, errors=errors, warnings=warnings)
        elif config.task_id == "molecules":
            _validate_molecules(config, config_path=path, errors=errors)
        elif config.task_id in {"multi-site", "federated"}:
            _validate_federated(config, config_path=path, errors=errors)
        else:
            warnings.append(f"Task '{config.task_id}' is provided by a plugin; only common config validation was run.")

        _validate_privacy(config, errors)
        _validate_uncertainty(config, errors)
        _validate_reports(config, errors=errors, warnings=warnings)
    except Exception as exc:
        return ConfigValidationResult(config_path=config_path, errors=[str(exc)])

    return ConfigValidationResult(
        config_path=config_path,
        project=project,
        workflow=workflow,
        errors=errors,
        warnings=warnings,
    )