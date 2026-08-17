from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RunnerConfig:
    project: str
    workflow: str
    raw: dict[str, Any]
    config_path: str | None = None

    @property
    def task_id(self) -> str:
        """Preferred community-facing name for the configured workflow."""

        return self.workflow


def load_config(path: str) -> RunnerConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file does not exist: {path}")
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Config must be a YAML mapping.")

    project = str(payload.get("project", config_path.stem))
    task_value = payload.get("task")
    workflow_value = payload.get("workflow")
    if task_value and workflow_value and str(task_value).strip().lower() != str(workflow_value).strip().lower():
        raise ValueError("Config cannot set different values for 'task' and legacy 'workflow'.")
    task_id = str(task_value or workflow_value or "").strip().lower()
    if not task_id:
        raise ValueError("Config must define 'task' (preferred) or legacy 'workflow'.")
    return RunnerConfig(
        project=project,
        workflow=task_id,
        raw=payload,
        config_path=str(config_path.resolve()),
    )


def section(config: RunnerConfig, name: str) -> dict[str, Any]:
    value = config.raw.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Config section '{name}' must be a mapping.")
    return value


def required(section_data: dict[str, Any], key: str, *, section_name: str) -> Any:
    if key not in section_data or section_data[key] in (None, ""):
        raise ValueError(f"Missing required config value: {section_name}.{key}")
    return section_data[key]
