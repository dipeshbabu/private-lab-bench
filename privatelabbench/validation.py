from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from privatelabbench.config import RunnerConfig, load_config, required, section
from privatelabbench.privacy.dp import PrivacyConfig


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
    except Exception as exc:  # noqa: BLE001 - validation should return actionable user-facing errors
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
    if value not in (None, "", "regression", "classification"):
        errors.append("input.task_type must be 'regression' or 'classification' when provided.")


def _validate_privacy(config: RunnerConfig, errors: list[str]) -> None:
    privacy = section(config, "privacy")
    try:
        PrivacyConfig(
            mode=str(privacy.get("mode", "none")),
            epsilon=float(privacy.get("epsilon", 8.0)),
            sensitivity=float(privacy.get("sensitivity", 1.0)),
            seed=int(privacy.get("seed", 13)),
        ).validate()
    except Exception as exc:  # noqa: BLE001 - validation should collect user-facing errors
        errors.append(f"Invalid privacy config: {exc}")


def _validate_reports(config: RunnerConfig, *, errors: list[str], warnings: list[str]) -> None:
    report = section(config, "report")
    defaults = {
        "markdown": f"reports/{config.project}_{config.workflow}_eval.md",
        "json": f"reports/{config.project}_{config.workflow}_eval.json",
        "manifest": f"reports/{config.project}_{config.workflow}_manifest.json",
    }
    for key, default in defaults.items():
        _validate_output_path(
            report.get(key, default),
            label=f"report.{key}",
            errors=errors,
            warnings=warnings,
        )
    audit = section(config, "audit")
    _validate_output_path(
        audit.get("path", f"reports/{config.project}_audit.jsonl"),
        label="audit.path",
        errors=errors,
        warnings=warnings,
    )


def _validate_predictions(config: RunnerConfig, *, config_path: Path, errors: list[str]) -> None:
    input_cfg = section(config, "input")
    path_value = required(input_cfg, "path", section_name="input")
    target = str(required(input_cfg, "target_column", section_name="input"))
    prediction_column = str(required(input_cfg, "prediction_column", section_name="input"))
    split_column = input_cfg.get("split_column")
    _validate_task_type(input_cfg.get("task_type"), errors)
    path = _validate_input_file(path_value, config_path=config_path, errors=errors)
    if path is None:
        return
    required_columns = {target, prediction_column}
    if split_column:
        required_columns.add(str(split_column))
    _require_columns(path, _csv_columns(path), required_columns, errors)


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
        if workflow == "predictions":
            _validate_predictions(config, config_path=path, errors=errors)
        elif workflow == "molecules":
            _validate_molecules(config, config_path=path, errors=errors)
        elif workflow == "federated":
            _validate_federated(config, config_path=path, errors=errors)
        _validate_privacy(config, errors)
        _validate_reports(config, errors=errors, warnings=warnings)
    except Exception as exc:  # noqa: BLE001 - validation command should report failures, not traceback
        return ConfigValidationResult(config_path=config_path, errors=[str(exc)])

    return ConfigValidationResult(
        config_path=config_path,
        project=project,
        workflow=workflow,
        errors=errors,
        warnings=warnings,
    )
