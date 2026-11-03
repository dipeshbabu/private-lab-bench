"""Immutable, data-independent evaluation rules discovered locally or from packages."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
from importlib import metadata
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

import yaml

from privatelabbench.eval.paired_comparison import PairedComparisonConfig
from privatelabbench.eval.uncertainty import BootstrapConfig
from privatelabbench.privacy.dp import PrivacyConfig
from privatelabbench.privacy.export import validate_policy
from privatelabbench.quality import validate_quality_policy

PROTOCOL_SCHEMA = "evaluation-protocol/v1"
ENTRYPOINT_GROUP = "privatelabbench.protocols"
PROTOCOL_ROOT = Path(__file__).parent / "data" / "protocols"
ID_PATTERN = r"plb://[a-z0-9][a-z0-9-]*(?:/[a-z0-9][a-z0-9-]*)+"
VERSION_PATTERN = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
WITHDRAWN_PROTOCOLS = {"plb://generic/binary@1.0.0": "Binary label order was unspecified. Re-evaluate with plb://generic/binary@1.0.1 or an explicit versioned definition with ordered class labels."}
TASK_METRICS = {
    "regression": {"mae", "rmse", "r2"},
    "classification": {"accuracy", "f1", "auroc"},
    "multiclass": {"accuracy", "macro_f1", "weighted_f1", "log_loss", "macro_auroc_ovr"},
}
ARTIFACT_VERSIONS = {
    "report": "0.2", "receipt": "evaluation-receipt/v1",
    "uncertainty": "uncertainty/v1", "comparison": "paired-comparison-artifact/v1",
}


def _object(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{label} must define exactly: {', '.join(sorted(fields))}")
    return dict(value)


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value) or len(set(value)) != len(value):
        raise ValueError(f"{label} must be a list of unique, nonempty strings")
    return value


def _typed_settings(value: Any, defaults: Mapping[str, Any], label: str) -> dict[str, Any]:
    settings = _object(value, set(defaults), label)
    for key, default in defaults.items():
        item = settings[key]
        if default is None:
            valid = item is None or isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item)
        elif isinstance(default, float):
            valid = isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item)
        else:
            valid = type(item) is type(default)
        if not valid:
            raise ValueError(f"Invalid {label}.{key} type or non-finite value")
    if "seed" in settings and settings["seed"] < 0:
        raise ValueError(f"{label}.seed must be nonnegative")
    return settings


@dataclass(frozen=True)
class EvaluationProtocol:
    # Bytes prevent callers from mutating rules after their identity is computed.
    _canonical: bytes

    @classmethod
    def from_dict(cls, value: Any) -> EvaluationProtocol:
        fields = {"schema_version", "id", "version", "task", "task_type", "input_schema", "metrics", "primary_metric", "uncertainty", "slices", "comparison", "quality_gate", "privacy", "release", "artifact_versions"}
        if not isinstance(value, Mapping):
            raise ValueError("Protocol must be a mapping")
        raw = dict(value)
        design_payload = raw.pop("sampling_design", None)
        audit_payload = raw.pop("evaluation_design", None)
        ranking_payload = raw.pop("ranking", None)
        target_unit = raw.pop("target_unit", None)
        payload = deepcopy(_object(raw, fields, "Protocol"))
        if payload["schema_version"] != PROTOCOL_SCHEMA:
            raise ValueError(f"Expected {PROTOCOL_SCHEMA}")
        for key, pattern in (("id", ID_PATTERN), ("version", VERSION_PATTERN)):
            if not isinstance(payload[key], str) or not re.fullmatch(pattern, payload[key]):
                raise ValueError(f"Invalid protocol {key}")
        reference = f"{payload['id']}@{payload['version']}"
        if reference in WITHDRAWN_PROTOCOLS:
            raise ValueError(WITHDRAWN_PROTOCOLS[reference])
        if not isinstance(payload["task"], str) or not isinstance(payload["task_type"], str) or payload["task"] not in {"predictions", "tabular"} or payload["task_type"] not in TASK_METRICS:
            raise ValueError("Protocol v1 supports prediction-table tasks: predictions/tabular and regression/classification/multiclass")
        metrics = _strings(payload["metrics"], "metrics")
        if not metrics or not set(metrics) <= TASK_METRICS[payload["task_type"]] or payload["primary_metric"] not in metrics:
            raise ValueError("Protocol metrics and primary_metric must be supported by its task_type")
        schema = _object(payload["input_schema"], {"schema_version", "require_sample_id", "class_labels"}, "input_schema")
        labels = _strings(schema["class_labels"], "input_schema.class_labels")
        if schema["schema_version"] != "prediction-table/v1" or not isinstance(schema["require_sample_id"], bool):
            raise ValueError("Protocol requires prediction-table/v1 and boolean require_sample_id")
        if (payload["task_type"] == "multiclass" and len(labels) < 3) or (payload["task_type"] == "classification" and len(labels) != 2) or (payload["task_type"] == "regression" and labels):
            raise ValueError("Declare ordered class_labels: two for binary, at least three for multiclass, empty for regression")
        uncertainty = _typed_settings(payload["uncertainty"], asdict(BootstrapConfig()), "uncertainty")
        BootstrapConfig(**uncertainty).validate()
        slices = _object(payload["slices"], {"required", "optional", "min_size"}, "slices")
        required = _strings(slices["required"], "slices.required")
        optional = _strings(slices["optional"], "slices.optional")
        if set(required) & set(optional) or type(slices["min_size"]) is not int or slices["min_size"] < 2:
            raise ValueError("Protocol slices must be disjoint and min_size must be at least two")
        comparison_defaults = asdict(PairedComparisonConfig(metric=payload["primary_metric"]))
        comparison = _typed_settings(payload["comparison"], comparison_defaults, "comparison")
        if comparison["metric"] not in metrics:
            raise ValueError("Protocol comparison metric must be declared in metrics")
        PairedComparisonConfig(**comparison).validate()
        privacy = _typed_settings(payload["privacy"], asdict(PrivacyConfig()), "privacy")
        if privacy["mode"] == "dp":
            raise ValueError("Use the explicit metric_perturbation name; it provides no formal DP guarantee")
        PrivacyConfig(**privacy).validate()
        release = validate_policy(payload["release"])
        if release.get("enabled", False):
            raise ValueError("Protocol release defaults must be disabled; the data owner must explicitly opt in")
        payload["release"] = release
        if payload["artifact_versions"] != ARTIFACT_VERSIONS:
            raise ValueError("Incompatible protocol artifact_versions")
        if payload["quality_gate"] is not None:
            gate = validate_quality_policy(payload["quality_gate"])
            used = set(gate.get("metric", {}))
            if gate.get("baseline"):
                used.add(gate["baseline"]["metric"])
            for key, item in gate.get("slices", {}).items():
                if key == "critical":
                    used.update(rule["metric"] for rule in item.values())
                else:
                    used.add(key.removeprefix("worst_").rsplit("_", 1)[0])
            if not used <= set(metrics):
                raise ValueError("Protocol quality gates must use declared metrics")
        if design_payload is not None:
            from privatelabbench.eval.sampling import sampling_design
            design = sampling_design(design_payload)
            if not {column for column, value in design.critical_slices} <= set(required + optional):
                raise ValueError("Protocol critical-slice columns must be declared in its required/optional slices")
            payload["sampling_design"] = design.as_dict()
        if audit_payload is not None:
            from privatelabbench.design_audit import EvaluationDesign
            payload["evaluation_design"] = EvaluationDesign.from_dict(audit_payload).as_dict()
        if ranking_payload is not None:
            ranking = _object(ranking_payload, {"metric", "rule", "practical_tie_tolerance", "require_uncertainty"}, "ranking")
            tolerance = ranking["practical_tie_tolerance"]
            if ranking["metric"] != payload["primary_metric"] or ranking["rule"] != "conservative_interval_ties" or type(ranking["require_uncertainty"]) is not bool or isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or tolerance < 0:
                raise ValueError("Ranking must explicitly use the primary metric and a finite nonnegative practical tie tolerance")
            if ranking["require_uncertainty"] and not uncertainty["enabled"]:
                raise ValueError("Ranking with uncertainty requires enabled protocol uncertainty")
            payload["ranking"] = deepcopy(ranking)
        if target_unit is not None:
            if not isinstance(target_unit,str) or not target_unit.strip() or len(target_unit)>128 or any(ord(char)<32 for char in target_unit):
                raise ValueError("Protocol target_unit must be a bounded unit declaration")
            payload["target_unit"] = target_unit
        return cls(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8"))

    def as_dict(self) -> dict[str, Any]:
        return json.loads(self._canonical)

    @property
    def ref(self) -> str:
        payload = self.as_dict()
        return f"{payload['id']}@{payload['version']}"

    @property
    def sha256(self) -> str:
        return sha256(self._canonical).hexdigest()

    def identity(self) -> dict[str, Any]:
        payload = self.as_dict()
        return {"id": payload["id"], "version": payload["version"], "sha256": self.sha256, "metrics": payload["metrics"], "primary_metric": payload["primary_metric"]}

    def comparison_config(self) -> PairedComparisonConfig:
        return PairedComparisonConfig(**self.as_dict()["comparison"])


def load_protocol(path: str | Path) -> EvaluationProtocol:
    return EvaluationProtocol.from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


def discover_protocols() -> tuple[EvaluationProtocol, ...]:
    protocols = [load_protocol(path) for path in sorted(PROTOCOL_ROOT.glob("*.yaml"))]
    entry_points = metadata.entry_points()
    selected = entry_points.select(group=ENTRYPOINT_GROUP) if hasattr(entry_points, "select") else entry_points.get(ENTRYPOINT_GROUP, ())
    for entry in selected:
        provider = entry.load()
        produced = provider() if callable(provider) else provider
        items = [produced] if isinstance(produced, (EvaluationProtocol, Mapping)) else produced
        for item in items:
            protocols.append(item if isinstance(item, EvaluationProtocol) else EvaluationProtocol.from_dict(item))
    by_ref: dict[str, EvaluationProtocol] = {}
    for protocol in protocols:
        if protocol.ref in by_ref and protocol.sha256 != by_ref[protocol.ref].sha256:
            raise ValueError(f"Conflicting definitions for immutable protocol {protocol.ref}; publish a new version")
        by_ref[protocol.ref] = protocol
    return tuple(by_ref[key] for key in sorted(by_ref))


def resolve_protocol(reference: str, *, base: Path | None = None) -> EvaluationProtocol:
    if reference in WITHDRAWN_PROTOCOLS:
        raise ValueError(WITHDRAWN_PROTOCOLS[reference])
    if reference.startswith("plb://"):
        if "@" not in reference:
            raise ValueError("Protocol references require an explicit semantic version: plb://namespace/name@1.0.0")
        for protocol in discover_protocols():
            if protocol.ref == reference:
                return protocol
        raise ValueError(f"Protocol is not installed: {reference}; install its provider or supply a local YAML file")
    path = Path(reference)
    if not path.is_absolute() and base is not None:
        path = base / path
    return load_protocol(path)


def _bind(existing: Any, fixed: Any, label: str) -> Any:
    if existing is not None:
        if isinstance(fixed, dict) and isinstance(existing, dict):
            if set(existing) - set(fixed):
                raise ValueError(f"Unknown protocol-bound setting in {label}")
            for key, item in existing.items():
                _bind(item, fixed[key], f"{label}.{key}")
        elif existing != fixed or (type(existing) is not type(fixed) and not (type(existing) in {int, float} and type(fixed) in {int, float})):
            raise ValueError(f"{label} conflicts with the versioned protocol; choose a new protocol version")
    return deepcopy(fixed)


def apply_protocol(payload: Mapping[str, Any], protocol: EvaluationProtocol) -> dict[str, Any]:
    """Bind scientific settings while retaining owner-controlled paths and release consent."""
    result = deepcopy(dict(payload))
    rules = protocol.as_dict()
    result["evaluation"] = _bind(result.get("evaluation"), {"primary_metric": rules["primary_metric"]}, "evaluation")
    from privatelabbench.eval.sampling import sampling_design
    fixed_design = sampling_design(rules.get("sampling_design"))
    requested_design = sampling_design(result.get("sampling_design"))
    if requested_design is not None and (fixed_design is None or requested_design != fixed_design):
        raise ValueError("sampling_design conflicts with the versioned protocol; declare it in a new protocol version")
    if fixed_design:
        result["sampling_design"] = fixed_design.as_dict()
    from privatelabbench.design_audit import EvaluationDesign
    fixed_audit = EvaluationDesign.from_dict(rules["evaluation_design"]) if rules.get("evaluation_design") else None
    requested_audit = EvaluationDesign.from_dict(result["evaluation_design"]) if result.get("evaluation_design") else None
    if requested_audit and (fixed_audit is None or requested_audit != fixed_audit):
        raise ValueError("evaluation_design conflicts with the versioned protocol; declare a new protocol version")
    if fixed_audit:
        result["evaluation_design"] = fixed_audit.as_dict()
    for key in ("task", "uncertainty", "privacy", "quality_gate"):
        result[key] = _bind(result.get(key), rules[key], key)
    if result["quality_gate"] is None:
        result.pop("quality_gate")
    if result.get("workflow") and result["workflow"] != rules["task"]:
        raise ValueError("workflow conflicts with protocol task")
    input_cfg = result.setdefault("input", {})
    if not isinstance(input_cfg, dict):
        raise ValueError("input must be a mapping")
    for key, fixed in {"task_type": rules["task_type"], "require_sample_id": rules["input_schema"]["require_sample_id"], "class_labels": rules["input_schema"]["class_labels"], "min_slice_size": rules["slices"]["min_size"]}.items():
        input_cfg[key] = _bind(input_cfg.get(key), fixed, f"input.{key}")
    chosen = _strings(input_cfg.get("slice_columns", rules["slices"]["required"]), "input.slice_columns")
    if not set(rules["slices"]["required"]) <= set(chosen) or not set(chosen) <= set(rules["slices"]["required"] + rules["slices"]["optional"]):
        raise ValueError("input.slice_columns must include required slices and only declared optional slices")
    input_cfg["slice_columns"] = chosen
    release = result.get("release", {})
    if not isinstance(release, dict):
        raise ValueError("release must be a mapping")
    release = validate_policy({**rules["release"], **release})
    if any(release[key] < rules["release"][key] for key in ("min_samples", "min_cell_size")) or rules["release"].get("require_privacy_audit", True) and not release.get("require_privacy_audit", True) or rules["release"].get("require_design_audit", False) and not release.get("require_design_audit", False):
        raise ValueError("Run release policy cannot weaken protocol disclosure thresholds or audit requirements")
    result["release"] = release
    result["protocol"] = protocol.ref
    return result
