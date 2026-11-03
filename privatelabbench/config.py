from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
    prepared_input: Any = field(default=None, repr=False, compare=False)
    design_audits: tuple[dict[str, Any], ...] = field(
        default=(), repr=False, compare=False
    )
    validation_context: dict[str, Any] | None = field(
        default=None, repr=False, compare=False
    )
    definition_paths: tuple[str, ...] = ()

    @property
    def task_id(self) -> str:
        """Preferred community-facing name for the configured workflow."""

        return self.workflow


def load_config(path: str, *, protocol_override: str | None = None) -> RunnerConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file does not exist: {path}")
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    definition_paths = [str(config_path.resolve())]
    if not isinstance(payload, dict):
        raise ValueError("Config must be a YAML mapping.")
    if payload.get("evaluation_design") is not None:
        from privatelabbench.design_audit import EvaluationDesign

        value = payload["evaluation_design"]
        if isinstance(value, str):
            design_path = config_path.resolve().parent / value
            definition_paths.append(str(design_path.resolve()))
            value = yaml.safe_load(design_path.read_text(encoding="utf-8"))
        payload["evaluation_design"] = EvaluationDesign.from_dict(value).as_dict()

    protocol = None
    reference = protocol_override or payload.get("protocol")
    if reference is not None:
        from privatelabbench.protocols import apply_protocol, resolve_protocol

        if not isinstance(reference, str):
            raise ValueError(
                "protocol must be an exact plb:// reference or a local YAML path"
            )
        protocol = resolve_protocol(
            reference,
            base=Path.cwd() if protocol_override else config_path.resolve().parent,
        )
        if not reference.startswith("plb://"):
            base = Path.cwd() if protocol_override else config_path.resolve().parent
            definition_paths.append(str((base / reference).resolve()))
        if protocol_override and payload.get("protocol"):
            configured = resolve_protocol(
                payload["protocol"], base=config_path.resolve().parent
            )
            if not payload["protocol"].startswith("plb://"):
                definition_paths.append(
                    str((config_path.resolve().parent / payload["protocol"]).resolve())
                )
            if configured.sha256 != protocol.sha256:
                raise ValueError(
                    "--protocol conflicts with the protocol declared in the config"
                )
        if (
            payload.get("protocol_sha256") is not None
            and payload["protocol_sha256"] != protocol.sha256
        ):
            raise ValueError(
                "Protocol digest changed from protocol_sha256; review the definition and pin its new version explicitly"
            )
        payload = apply_protocol(payload, protocol)
    elif payload.get("protocol_sha256") is not None:
        raise ValueError("protocol_sha256 requires a protocol reference")
    if payload.get("sampling_design") is not None:
        from privatelabbench.eval.sampling import sampling_design

        payload["sampling_design"] = sampling_design(
            payload["sampling_design"]
        ).as_dict()
    if payload.get("evaluation_design") is not None:
        rules = payload["evaluation_design"]
        input_cfg = payload.setdefault("input", {})
        if not isinstance(input_cfg, dict):
            raise ValueError("input must be a mapping")
        if (
            input_cfg.get("sample_id_column", rules["sample_id_column"])
            != rules["sample_id_column"]
            or input_cfg.get("require_sample_id", True) is not True
        ):
            raise ValueError(
                "Evaluation-design runs require the declared stable sample-ID column"
            )
        input_cfg["sample_id_column"] = rules["sample_id_column"]
        input_cfg["require_sample_id"] = True
        if (
            rules["label_column"] is not None
            and input_cfg.get("target_column") != rules["label_column"]
        ):
            raise ValueError(
                "evaluation_design.label_column must match input.target_column"
            )

    project = str(payload.get("project", config_path.stem))
    task_value = payload.get("task")
    workflow_value = payload.get("workflow")
    if (
        task_value
        and workflow_value
        and str(task_value).strip().lower() != str(workflow_value).strip().lower()
    ):
        raise ValueError(
            "Config cannot set different values for 'task' and legacy 'workflow'."
        )
    task_id = str(task_value or workflow_value or "").strip().lower()
    if not task_id:
        raise ValueError("Config must define 'task' (preferred) or legacy 'workflow'.")
    return RunnerConfig(
        project=project,
        workflow=task_id,
        raw=payload,
        config_path=str(config_path.resolve()),
        protocol=protocol,
        definition_paths=tuple(definition_paths),
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
