from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


SUPPORTED_WORKFLOWS = {"molecules", "federated", "predictions"}


@dataclass(frozen=True)
class RunnerConfig:
    project: str
    workflow: str
    raw: dict[str, Any]


def load_config(path: str) -> RunnerConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file does not exist: {path}")
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Config must be a YAML mapping.")

    project = str(payload.get("project", config_path.stem))
    workflow = str(payload.get("workflow", "")).strip().lower()
    if workflow not in SUPPORTED_WORKFLOWS:
        raise ValueError(f"Unsupported workflow '{workflow}'. Supported workflows: {', '.join(sorted(SUPPORTED_WORKFLOWS))}")
    return RunnerConfig(project=project, workflow=workflow, raw=payload)


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
