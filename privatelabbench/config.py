from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from privatelabbench.protocols import EvaluationProtocol


@dataclass(frozen=True)
class RunnerConfig:
    project: str
    workflow: str
    raw: dict[str, Any]
    config_path: str | None = None
    protocol: EvaluationProtocol | None = None

    @property
    def task_id(self) -> str:
        """Preferred community-facing name for the configured workflow."""

        return self.workflow


def load_config(path: str, *, protocol_override: str | None = None) -> RunnerConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file does not exist: {path}")
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Config must be a YAML mapping.")

    protocol = None
    reference = protocol_override or payload.get("protocol")
    if reference is not None:
        from privatelabbench.protocols import apply_protocol, resolve_protocol
        if not isinstance(reference, str):
            raise ValueError("protocol must be an exact plb:// reference or a local YAML path")
        protocol = resolve_protocol(reference, base=Path.cwd() if protocol_override else config_path.resolve().parent)
        if protocol_override and payload.get("protocol"):
            configured = resolve_protocol(payload["protocol"], base=config_path.resolve().parent)
            if configured.sha256 != protocol.sha256:
                raise ValueError("--protocol conflicts with the protocol declared in the config")
        if payload.get("protocol_sha256") is not None and payload["protocol_sha256"] != protocol.sha256:
            raise ValueError("Protocol digest changed from protocol_sha256; review the definition and pin its new version explicitly")
        payload = apply_protocol(payload, protocol)
    elif payload.get("protocol_sha256") is not None:
        raise ValueError("protocol_sha256 requires a protocol reference")
    if payload.get("sampling_design") is not None:
        from privatelabbench.eval.sampling import sampling_design
        payload["sampling_design"] = sampling_design(payload["sampling_design"]).as_dict()

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
        protocol=protocol,
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
