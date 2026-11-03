"""Local split-integrity evidence, never a proof of undisclosed training history."""

from __future__ import annotations

from copy import deepcopy
import csv
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from io import BytesIO, TextIOWrapper
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

import numpy as np
import pandas as pd

from privatelabbench.reports.integrity import attach_integrity_metadata

DESIGN_SCHEMA = "evaluation-design/v1"
AUDIT_SCHEMA = "evaluation-design-audit/v1"
ALGORITHM = "split-audit/v1"
ROLES = {"train", "validation", "test"}
POLICIES = {"allow", "warn", "forbid"}
LIMITATIONS = [
    "Findings apply only to the supplied records, identifiers, and declared rules.",
    "A negative scoped audit cannot exclude undisclosed pretraining or unknown training records.",
    "Reference completeness and dataset descriptions are declarations by the evaluator.",
    "Scientific split checks are not privacy guarantees or proof of model execution.",
]
CHECKS = {
    "training_reference_coverage",
    "evaluation_duplicate_ids",
    "reference_duplicate_ids",
    "sample_id_overlap",
    "entity_overlap",
    "repeated_entities",
    "conflicting_labels",
    "group_overlap",
    "chronology",
    "invalid_molecules",
    "molecular_identity",
    "scaffold_overlap",
    "near_duplicates",
}


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return dict(value)


def _columns(value: Any, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(f"{label} must list unique, nonempty column names")
    return value


def _policy(value: Any, label: str) -> None:
    if not isinstance(value, str) or value not in POLICIES:
        raise ValueError(f"{label} must be allow, warn, or forbid")


def _iso(value: Any) -> pd.Timestamp:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?",
        value,
    ):
        raise ValueError(
            "Chronology uses ISO dates/timestamps; naive dates/times are declared UTC"
        )
    result = pd.Timestamp(value)
    return (
        result.tz_localize("UTC") if result.tzinfo is None else result.tz_convert("UTC")
    )


@dataclass(frozen=True)
class EvaluationDesign:
    _canonical: bytes

    @classmethod
    def from_dict(cls, value: Any) -> EvaluationDesign:
        supplied = _object(value, "evaluation design")
        defaults = {
            "schema_version": DESIGN_SCHEMA,
            "unit": "sample",
            "sample_id_column": "sample_id",
            "entity_columns": [],
            "group_columns": [],
            "label_column": None,
            "split_column": None,
            "evaluation_partition": "test",
            "reference_partition": "train",
            "partition_labels": {
                "train": ["train"],
                "validation": ["validation"],
                "test": ["test"],
            },
            "forbidden_pairs": [
                ["train", "test"],
                ["train", "validation"],
                ["validation", "test"],
            ],
            "duplicate_ids": "forbid",
            "reference_duplicate_ids": "warn",
            "repeated_entities": "allow",
            "conflicting_labels": "warn",
            "label_tolerance": 0.0,
            "overlap": {
                "sample_ids": "forbid",
                "entities": "forbid",
                "groups": "forbid",
            },
            "chronology": None,
            "exclusions": [],
            "adapter": None,
        }
        if supplied.get("schema_version") != DESIGN_SCHEMA or set(supplied) - set(
            defaults
        ):
            raise ValueError(
                "Expected evaluation-design/v1 and supported design fields"
            )
        data = {**deepcopy(defaults), **deepcopy(supplied)}
        if not isinstance(data["unit"], str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_-]{0,63}", data["unit"]
        ):
            raise ValueError("Declare a short evaluation-unit name")
        for key in ("sample_id_column", "label_column", "split_column"):
            if data[key] is not None and (
                not isinstance(data[key], str) or not data[key].strip()
            ):
                raise ValueError(f"Invalid {key}")
        if data["sample_id_column"] is None:
            raise ValueError("sample_id_column is required for a scoped split audit")
        for key in ("entity_columns", "group_columns"):
            _columns(data[key], key)
        for key in ("evaluation_partition", "reference_partition"):
            if data[key] not in ROLES:
                raise ValueError("Partitions must be train, validation, or test")
        if data["evaluation_partition"] == data["reference_partition"]:
            raise ValueError(
                "Evaluation and training-reference partitions must be distinct"
            )
        labels = _object(data["partition_labels"], "partition_labels")
        if set(labels) != ROLES:
            raise ValueError(
                "partition_labels must define train, validation, and test aliases"
            )
        all_labels = []
        for role, aliases in labels.items():
            _columns(aliases, f"partition_labels.{role}")
            all_labels.extend(aliases)
        if len(set(all_labels)) != len(all_labels):
            raise ValueError("A split alias cannot name multiple partitions")
        pairs = data["forbidden_pairs"]
        if not isinstance(pairs, list) or any(
            not isinstance(pair, list)
            or len(pair) != 2
            or any(role not in ROLES for role in pair)
            or pair[0] == pair[1]
            for pair in pairs
        ):
            raise ValueError(
                "forbidden_pairs must contain distinct partition-role pairs"
            )
        if len({tuple(sorted(pair)) for pair in pairs}) != len(pairs):
            raise ValueError("Forbidden partition pairs cannot repeat")
        for key in (
            "duplicate_ids",
            "reference_duplicate_ids",
            "repeated_entities",
            "conflicting_labels",
        ):
            _policy(data[key], key)
        overlap = _object(data["overlap"], "overlap")
        if set(overlap) - {"sample_ids", "entities", "groups"}:
            raise ValueError("Unsupported overlap policy")
        data["overlap"] = {**defaults["overlap"], **overlap}
        for key, policy in data["overlap"].items():
            _policy(policy, f"overlap.{key}")
        tolerance = data["label_tolerance"]
        if (
            isinstance(tolerance, bool)
            or not isinstance(tolerance, (int, float))
            or not math.isfinite(tolerance)
            or tolerance < 0
        ):
            raise ValueError("label_tolerance must be finite and nonnegative")
        chronology = data["chronology"]
        if chronology is not None:
            chronology = _object(chronology, "chronology")
            if (
                set(chronology) - {"column", "cutoff", "strictly_before", "timezone"}
                or not isinstance(chronology.get("column"), str)
                or not chronology["column"]
            ):
                raise ValueError("chronology needs a column and supported UTC rules")
            chronology = {
                "cutoff": None,
                "strictly_before": True,
                "timezone": "UTC",
                **chronology,
            }
            if (
                type(chronology["strictly_before"]) is not bool
                or chronology["timezone"] != "UTC"
            ):
                raise ValueError(
                    "Chronology v1 requires boolean strictly_before and declared UTC normalization"
                )
            if isinstance(chronology["cutoff"], date):
                chronology["cutoff"] = chronology["cutoff"].isoformat()
            if chronology["cutoff"] is not None:
                _iso(chronology["cutoff"])
            data["chronology"] = chronology
        if not isinstance(data["exclusions"], list):
            raise ValueError(
                "exclusions must be a list of predeclared eligibility rules"
            )
        exclusions = []
        for rule in data["exclusions"]:
            rule = _object(rule, "exclusion")
            if (
                set(rule) - {"column", "operator", "value", "reason"}
                or not isinstance(rule.get("column"), str)
                or not rule["column"]
                or rule.get("operator")
                not in {"equals", "less_than", "greater_than", "is_missing"}
            ):
                raise ValueError(
                    "Exclusions require a column and equals/less_than/greater_than/is_missing"
                )
            rule.setdefault("value", None)
            rule.setdefault("reason", "declared_exclusion")
            if not isinstance(rule["reason"], str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,64}", rule["reason"]
            ):
                raise ValueError("Exclusion reasons must be short declarations")
            item = rule["value"]
            if (rule["operator"] == "is_missing") != (item is None):
                raise ValueError(
                    "Use is_missing with a null value, or a non-null comparison value"
                )
            if (
                item is not None
                and not isinstance(item, (str, int, float, bool))
                or isinstance(item, (int, float))
                and not math.isfinite(item)
            ):
                raise ValueError(
                    "Exclusions accept scalar values, never executable expressions or identifier lists"
                )
            if rule["operator"] in {"less_than", "greater_than"} and (
                isinstance(item, bool) or not isinstance(item, (int, float))
            ):
                raise ValueError(
                    "Numeric eligibility thresholds must be finite numbers"
                )
            if rule["operator"] != "is_missing" and rule["column"] in {
                data["sample_id_column"],
                *data["entity_columns"],
                *data["group_columns"],
            }:
                raise ValueError(
                    "Use generic eligibility/QC rules, not individual identifier exclusions"
                )
            exclusions.append(rule)
        data["exclusions"] = exclusions
        if data["adapter"] is not None:
            adapter = _object(data["adapter"], "design adapter")
            allowed = {
                "name",
                "smiles_column",
                "canonical_isomeric",
                "scaffold_include_chirality",
                "identity_overlap",
                "scaffold_overlap",
                "near_duplicates",
            }
            if (
                set(adapter) - allowed
                or adapter.get("name") != "rdkit-molecule/v1"
                or not isinstance(adapter.get("smiles_column"), str)
                or not adapter["smiles_column"]
            ):
                raise ValueError(
                    "Explicitly select the optional rdkit-molecule/v1 adapter and SMILES column"
                )
            adapter = {
                "canonical_isomeric": True,
                "scaffold_include_chirality": False,
                "identity_overlap": "forbid",
                "scaffold_overlap": "allow",
                "near_duplicates": None,
                **adapter,
            }
            if any(
                type(adapter[key]) is not bool
                for key in ("canonical_isomeric", "scaffold_include_chirality")
            ):
                raise ValueError("Molecule canonicalization options must be boolean")
            for key in ("identity_overlap", "scaffold_overlap"):
                _policy(adapter[key], key)
            near = adapter["near_duplicates"]
            if near is not None:
                near = _object(near, "near duplicates")
                if set(near) - {"threshold", "radius", "bits", "max_pairs", "policy"}:
                    raise ValueError("Unsupported near-duplicate settings")
                near = {
                    "threshold": 0.9,
                    "radius": 2,
                    "bits": 2048,
                    "max_pairs": 100000,
                    "policy": "warn",
                    **near,
                }
                if (
                    isinstance(near["threshold"], bool)
                    or not isinstance(near["threshold"], (int, float))
                    or not 0 < near["threshold"] <= 1
                ):
                    raise ValueError("Tanimoto threshold must be between zero and one")
                if any(
                    type(near[key]) is not int or near[key] < minimum
                    for key, minimum in (("radius", 1), ("bits", 64), ("max_pairs", 1))
                ):
                    raise ValueError("Invalid Morgan fingerprint or comparison budget")
                _policy(near["policy"], "near duplicate policy")
                adapter["near_duplicates"] = near
            data["adapter"] = adapter
        return cls(
            json.dumps(
                data,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        )

    def as_dict(self) -> dict[str, Any]:
        return json.loads(self._canonical)

    @property
    def sha256(self) -> str:
        return sha256(self._canonical).hexdigest()


class DesignAuditFailure(ValueError):
    pass


@dataclass(frozen=True)
class PreparedEvaluation:
    frame: pd.DataFrame
    artifact: dict[str, Any]


def _read(
    path: str | Path, columns: list[str], *, selected_columns: list[str] | None = None
) -> tuple[pd.DataFrame, str]:
    content = Path(path).read_bytes()
    with TextIOWrapper(BytesIO(content), encoding="utf-8-sig", newline="") as stream:
        header = next(csv.reader(stream), [])
        if (
            not header
            or len(set(header)) != len(header)
            or any(not item.strip() for item in header)
        ):
            raise ValueError("Audit CSVs require unique, nonempty column names")
        usecols = (
            [column for column in header if column in selected_columns]
            if selected_columns is not None
            else None
        )
        if usecols == []:
            usecols = header[:1]
        stream.seek(0)
        frame = pd.read_csv(
            stream, dtype={column: "string" for column in columns}, usecols=usecols
        )
    return frame, sha256(content).hexdigest()


def _roles(
    frame: pd.DataFrame,
    rules: Mapping[str, Any],
    fallback: str,
    *,
    allow_missing: bool = False,
) -> pd.Series:
    column = rules["split_column"]
    if column is None:
        return pd.Series(fallback, index=frame.index)
    if column not in frame:
        if not allow_missing:
            raise ValueError(
                "The declared evaluation split column is missing; use a null split_column only for an explicitly single-partition table"
            )
        return pd.Series(fallback, index=frame.index)
    aliases = {
        label: role
        for role, labels in rules["partition_labels"].items()
        for label in labels
    }
    values = frame[column].astype("string")
    result = values.map(aliases)
    if result.isna().any():
        raise ValueError(
            "Split values are missing or absent from the declared partition aliases"
        )
    return result


def _excluded(frame: pd.DataFrame, rules: Mapping[str, Any]) -> pd.Series:
    result = pd.Series(False, index=frame.index)
    for rule in rules["exclusions"]:
        column, operator, value = rule["column"], rule["operator"], rule["value"]
        if column not in frame:
            raise ValueError("A declared eligibility/QC column is missing")
        values = frame[column]
        if operator == "is_missing":
            matched = values.isna()
        elif operator == "equals":
            if (
                isinstance(value, str)
                and not values.dropna().map(lambda item: isinstance(item, str)).all()
            ):
                raise ValueError("String eligibility rules require a string QC column")
            if isinstance(value, bool):

                def boolean(item):
                    if pd.isna(item):
                        return pd.NA
                    if isinstance(item, (bool, np.bool_)):
                        return bool(item)
                    if isinstance(item, (int, float)) and item in (0, 1):
                        return bool(item)
                    if isinstance(item, str) and item.lower() in {
                        "true",
                        "false",
                        "0",
                        "1",
                    }:
                        return item.lower() in {"true", "1"}
                    raise ValueError(
                        "Boolean eligibility rules require true/false or zero/one QC values"
                    )

                values = values.map(boolean)
            matched = values.eq(value).fillna(False)
        else:
            numeric = pd.to_numeric(values, errors="raise")
            matched = (
                numeric.lt(value) if operator == "less_than" else numeric.gt(value)
            )
        result |= matched
    return result


def _evaluation_excluded(frame, roles, rules):
    result = pd.Series(False, index=frame.index)
    selected = roles.eq(rules["evaluation_partition"])
    if selected.any():
        result.loc[selected] = _excluded(frame.loc[selected], rules)
    return result


def select_eligible(
    path: str | Path,
    definition: EvaluationDesign,
    *,
    additional_identifier_columns: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Apply the same eligibility rules for config binding; this is not an audit."""
    rules = definition.as_dict()
    columns = [
        rules["sample_id_column"],
        *rules["entity_columns"],
        *rules["group_columns"],
        *additional_identifier_columns,
        *([rules["split_column"]] if rules["split_column"] else []),
    ]
    frame = pd.read_csv(path, dtype={column: "string" for column in columns})
    roles = _roles(frame, rules, rules["evaluation_partition"])
    return frame.loc[
        roles.eq(rules["evaluation_partition"])
        & ~_evaluation_excluded(frame, roles, rules)
    ].reset_index(drop=True)


def _keys(frame: pd.DataFrame, columns: list[str]) -> tuple[list[Any], bool]:
    if not columns or any(column not in frame for column in columns):
        return [None] * len(frame), False
    values = frame[columns]
    normalized = values.astype(str)
    missing = values.isna().any(axis=1) | normalized.apply(
        lambda column: column.str.strip().eq("")
    ).any(axis=1)
    keys = [
        None if absent else tuple(row)
        for row, absent in zip(normalized.itertuples(index=False, name=None), missing)
    ]
    return keys, not missing.any()


def _cross(keys: list[Any], roles: pd.Series, pairs: list[list[str]]) -> set[int]:
    groups: dict[str, dict[Any, list[int]]] = {}
    for index, (key, role) in enumerate(zip(keys, roles)):
        if key is not None:
            groups.setdefault(role, {}).setdefault(key, []).append(index)
    affected = set()
    for a, b in pairs:
        left, right = groups.get(a, {}), groups.get(b, {})
        for key in left.keys() & right.keys():
            affected.update(left[key])
            affected.update(right[key])
    return affected


def prepare_evaluation(
    path: str,
    definition: EvaluationDesign,
    *,
    training_reference: str | None = None,
    reference_complete: bool = False,
    additional_identifier_columns: tuple[str, ...] = (),
) -> PreparedEvaluation:
    if type(reference_complete) is not bool:
        raise ValueError("reference_complete must be an explicit boolean declaration")
    rules = definition.as_dict()
    identifiers = list(
        dict.fromkeys(
            [
                *additional_identifier_columns,
                rules["sample_id_column"],
                *rules["entity_columns"],
                *rules["group_columns"],
                *([rules["split_column"]] if rules["split_column"] else []),
            ]
        )
    )
    original, digest = _read(path, identifiers)
    original_roles = _roles(original, rules, rules["evaluation_partition"])
    dropped = _evaluation_excluded(original, original_roles, rules)
    eligible = original.loc[~dropped].reset_index(drop=True)
    eligible_roles = original_roles.loc[~dropped].reset_index(drop=True)
    scored = eligible.loc[eligible_roles.eq(rules["evaluation_partition"])].reset_index(
        drop=True
    )
    if scored.empty:
        raise ValueError(
            "No evaluation rows remain in the declared partition after eligibility rules"
        )
    reference = None
    reference_digest = None
    if training_reference:
        needed = [
            *identifiers,
            *([rules["label_column"]] if rules["label_column"] else []),
            *([rules["chronology"]["column"]] if rules["chronology"] else []),
            *([rules["adapter"]["smiles_column"]] if rules["adapter"] else []),
        ]
        reference, reference_digest = _read(
            training_reference, identifiers, selected_columns=needed
        )
        roles = _roles(
            reference, rules, rules["reference_partition"], allow_missing=True
        )
        reference = reference.loc[roles.eq(rules["reference_partition"])].reset_index(
            drop=True
        )
    reference_present = reference is not None and len(reference) > 0
    frames = [eligible] + ([reference] if reference_present else [])
    combined = pd.concat(frames, ignore_index=True)
    roles = pd.concat(
        [eligible_roles]
        + (
            [pd.Series(rules["reference_partition"], index=reference.index)]
            if reference_present
            else []
        ),
        ignore_index=True,
    )
    findings, examples = {}, {}
    sample = rules["sample_id_column"]

    def finding(name, affected=(), *, policy="forbid", available=True, reason=None):
        indices = set(affected)
        status = (
            "fail"
            if indices and policy == "forbid"
            else (
                "warn"
                if indices and policy == "warn"
                else "not_testable" if not available else "pass"
            )
        )
        findings[name] = {
            "status": status,
            "affected_records": len(indices) if available or indices else None,
            "evidence_complete": bool(available),
            "policy": policy,
            "reason": reason
            or (
                "within_declared_policy"
                if status == "pass"
                else "declared_rule_violated" if indices else "evidence_unavailable"
            ),
        }
        if indices:
            examples[name] = [
                str(combined.iloc[index][sample])
                for index in sorted(indices)[:10]
                if sample in combined
            ]

    finding(
        "training_reference_coverage",
        policy="allow",
        available=reference_present and reference_complete,
        reason=(
            "provided_records_only"
            if reference_present and reference_complete
            else "training_reference_missing_or_incomplete"
        ),
    )
    for index, frame in enumerate(frames):
        offset = 0 if index == 0 else len(eligible)
        if sample not in frame:
            finding(
                "evaluation_duplicate_ids" if index == 0 else "reference_duplicate_ids",
                available=False,
            )
            continue
        values = frame[sample]
        bad = (
            values.isna()
            | values.astype(str).str.strip().eq("")
            | values.duplicated(keep=False)
        )
        finding(
            "evaluation_duplicate_ids" if index == 0 else "reference_duplicate_ids",
            np.flatnonzero(bad) + offset,
            policy=(
                rules["duplicate_ids"]
                if index == 0
                else rules["reference_duplicate_ids"]
            ),
        )
    coverage = reference_present and reference_complete
    for name, columns, policy in (
        ("sample_id_overlap", [sample], rules["overlap"]["sample_ids"]),
        ("entity_overlap", rules["entity_columns"], rules["overlap"]["entities"]),
    ):
        if not columns:
            continue
        keys, complete = _keys(combined, columns)
        affected = _cross(keys, roles, rules["forbidden_pairs"])
        finding(name, affected, policy=policy, available=complete and coverage)
        if name == "entity_overlap":
            grouped = {}
            for index, (key, role) in enumerate(zip(keys, roles)):
                if key is not None:
                    grouped.setdefault((role, key), []).append(index)
            sample_names = (
                combined[sample].astype(str).to_numpy() if sample in combined else None
            )
            repeated = {
                index
                for indices in grouped.values()
                if len(indices) > 1
                and (
                    sample_names is None
                    or len({sample_names[index] for index in indices}) > 1
                )
                for index in indices
            }
            finding(
                "repeated_entities",
                repeated,
                policy=rules["repeated_entities"],
                available=complete,
            )
            label = rules["label_column"]
            if label:
                conflicts = set()
                known = label in combined and not combined[label].isna().any()
                if label in combined:
                    entities = {}
                    labels = combined[label]
                    for index, (key, value) in enumerate(zip(keys, labels)):
                        if key is not None and pd.notna(value):
                            entities.setdefault(key, []).append(index)
                    for indices in entities.values():
                        if len(indices) < 2:
                            continue
                        values = labels.iloc[indices]
                        numeric = pd.to_numeric(values, errors="coerce")
                        if numeric.notna().all() and not np.isfinite(numeric).all():
                            known = False
                            continue
                        conflict = (
                            numeric.max() - numeric.min() > rules["label_tolerance"]
                            if numeric.notna().all()
                            else values.astype(str).nunique() > 1
                        )
                        if conflict:
                            conflicts.update(indices)
                finding(
                    "conflicting_labels",
                    conflicts,
                    policy=rules["conflicting_labels"],
                    available=bool(known and complete),
                )
    if rules["group_columns"]:
        group_matches = set()
        complete = coverage
        for column in rules["group_columns"]:
            keys, known = _keys(combined, [column])
            complete &= known
            group_matches.update(_cross(keys, roles, rules["forbidden_pairs"]))
        finding(
            "group_overlap",
            group_matches,
            policy=rules["overlap"]["groups"],
            available=bool(complete),
        )
    if rules["chronology"]:
        chronology = rules["chronology"]
        column = chronology["column"]
        timestamps, known = [], column in combined
        if known:
            for item in combined[column]:
                try:
                    timestamps.append(_iso(str(item)))
                except (ValueError, TypeError):
                    timestamps.append(pd.NaT)
                    known = False
        else:
            timestamps = [pd.NaT] * len(combined)
        time = pd.Series(timestamps, dtype="datetime64[ns, UTC]")
        training = roles.isin(
            ["train", "validation", rules["reference_partition"]]
        ) & ~roles.eq(rules["evaluation_partition"])
        evaluation = roles.eq(rules["evaluation_partition"])
        bad = pd.Series(False, index=combined.index)
        if evaluation.any() and training.any() and time[evaluation].notna().any():
            boundary = time[evaluation].min()
            bad |= training & (
                time.ge(boundary)
                if chronology["strictly_before"]
                else time.gt(boundary)
            )
        if chronology["cutoff"]:
            cutoff = _iso(chronology["cutoff"])
            bad |= training & (
                time.ge(cutoff) if chronology["strictly_before"] else time.gt(cutoff)
            )
            bad |= evaluation & time.lt(cutoff)
        finding("chronology", np.flatnonzero(bad), available=bool(known and coverage))
    adapter_version = None
    if rules["adapter"]:
        adapter_version = _molecule_checks(
            combined, roles, rules, finding, coverage=coverage
        )
    statuses = {finding["status"] for finding in findings.values()}
    status = (
        "fail"
        if "fail" in statuses
        else (
            "not_testable"
            if "not_testable" in statuses
            or any(not item["evidence_complete"] for item in findings.values())
            else "warn" if "warn" in statuses else "pass"
        )
    )
    summary = {
        "schema_version": AUDIT_SCHEMA,
        "algorithm": ALGORITHM,
        "status": status,
        "definition_sha256": definition.sha256,
        "training_reference_present": reference_present,
        "reference_declared_complete": reference_complete,
        "scope": "provided_records_only",
        "n_evaluation_records": len(scored),
        "n_input_records": len(original),
        "n_reference_records": len(reference) if reference_present else 0,
        "n_checked_records": len(combined),
        "excluded_evaluation_records": int(dropped.sum()),
        "findings": findings,
        "adapter": rules["adapter"]["name"] if rules["adapter"] else None,
        "adapter_version": adapter_version,
        "limitations": LIMITATIONS,
    }
    artifact = attach_integrity_metadata(
        {
            "schema_version": AUDIT_SCHEMA,
            "scope": "local",
            "audit": summary,
            "local": {
                "definition": rules,
                "evaluation_path": str(Path(path).resolve()),
                "evaluation_sha256": digest,
                "training_reference_path": (
                    str(Path(training_reference).resolve())
                    if training_reference
                    else None
                ),
                "training_reference_sha256": reference_digest,
                "examples": examples,
            },
        }
    )
    return PreparedEvaluation(scored, artifact)


def _molecule_checks(frame, roles, rules, finding, *, coverage):
    adapter = rules["adapter"]
    try:
        import rdkit
        from rdkit import Chem, DataStructs, rdBase
        from rdkit.Chem import rdFingerprintGenerator
        from rdkit.Chem.Scaffolds import MurckoScaffold
    except ImportError:
        finding(
            "molecular_identity", available=False, reason="optional_adapter_unavailable"
        )
        return None
    column = adapter["smiles_column"]
    if column not in frame:
        finding("molecular_identity", available=False, reason="molecule_column_missing")
        return rdkit.__version__
    molecules, identities, scaffolds, invalid = [], [], [], []
    missing = []
    with rdBase.BlockLogs():
        for index, value in enumerate(frame[column]):
            absent = pd.isna(value) or not str(value).strip()
            mol = Chem.MolFromSmiles(str(value)) if not absent else None
            molecules.append(mol)
            if mol is None:
                identities.append(None)
                scaffolds.append(None)
                (missing if absent else invalid).append(index)
            else:
                identities.append(
                    (
                        Chem.MolToSmiles(
                            mol, isomericSmiles=adapter["canonical_isomeric"]
                        ),
                    )
                )
                scaffold = MurckoScaffold.MurckoScaffoldSmiles(
                    mol=mol, includeChirality=adapter["scaffold_include_chirality"]
                )
                scaffolds.append((scaffold,) if scaffold else None)
    finding("invalid_molecules", invalid, available=not missing)
    complete = not invalid and not missing and coverage
    finding(
        "molecular_identity",
        _cross(identities, roles, rules["forbidden_pairs"]),
        policy=adapter["identity_overlap"],
        available=complete,
    )
    if adapter["scaffold_overlap"] != "allow":
        finding(
            "scaffold_overlap",
            _cross(scaffolds, roles, rules["forbidden_pairs"]),
            policy=adapter["scaffold_overlap"],
            available=complete
            and all(
                any(
                    key is not None and role == partition
                    for key, role in zip(scaffolds, roles)
                )
                for partition in {
                    rules["evaluation_partition"],
                    rules["reference_partition"],
                }
            ),
            reason="nonempty_scaffolds_only",
        )
    near = adapter["near_duplicates"]
    if near:
        by_role = {
            role: [
                index
                for index, (mol, item) in enumerate(zip(molecules, roles))
                if mol is not None and item == role
            ]
            for role in ROLES
        }
        pairs = sum(
            len(by_role[a]) * len(by_role[b]) for a, b in rules["forbidden_pairs"]
        )
        if pairs > near["max_pairs"]:
            finding("near_duplicates", available=False, reason="pair_budget_exceeded")
        else:
            generator = rdFingerprintGenerator.GetMorganGenerator(
                radius=near["radius"],
                fpSize=near["bits"],
                includeChirality=adapter["canonical_isomeric"],
            )
            fingerprints = [
                generator.GetFingerprint(mol) if mol is not None else None
                for mol in molecules
            ]
            affected = set()
            for a, b in rules["forbidden_pairs"]:
                targets = by_role[b]
                for index in by_role[a]:
                    similarity = DataStructs.BulkTanimotoSimilarity(
                        fingerprints[index],
                        [fingerprints[target] for target in targets],
                    )
                    for target, score in zip(targets, similarity):
                        if score >= near["threshold"]:
                            affected.update((index, target))
            finding(
                "near_duplicates",
                affected,
                policy=near["policy"],
                available=complete and pairs > 0,
                reason="morgan_tanimoto_heuristic",
            )
    return rdkit.__version__


def validate_audit_summary(value: Any) -> dict[str, Any]:
    """Validate self-consistency of a declared audit, not truth of its inputs."""
    audit = _object(value, "design audit summary")
    if audit.get("model_role") not in {None, "model_a", "model_b"}:
        raise ValueError("Unsupported audited model role")
    if (
        audit.get("schema_version") == AUDIT_SCHEMA
        and audit.get("status") == "withheld_small_audit_cells"
        and audit.get("scope") == "provided_records_only"
    ):
        return {
            "schema_version": AUDIT_SCHEMA,
            "status": "withheld_small_audit_cells",
            "scope": "provided_records_only",
            **({"model_role": audit["model_role"]} if audit.get("model_role") else {}),
        }
    if (
        audit.get("schema_version") != AUDIT_SCHEMA
        or audit.get("algorithm") != ALGORITHM
        or audit.get("scope") != "provided_records_only"
    ):
        raise ValueError("Unsupported design-audit schema or algorithm")
    if not isinstance(audit.get("definition_sha256"), str) or not re.fullmatch(
        r"[a-f0-9]{64}", audit["definition_sha256"]
    ):
        raise ValueError("Design audit requires its exact rule-definition digest")
    for key in ("training_reference_present", "reference_declared_complete"):
        if type(audit.get(key)) is not bool:
            raise ValueError("Design-audit reference declarations must be boolean")
    for key in (
        "n_evaluation_records",
        "n_input_records",
        "n_reference_records",
        "n_checked_records",
        "excluded_evaluation_records",
    ):
        if type(audit.get(key)) is not int or audit[key] < 0:
            raise ValueError("Invalid design-audit record count")
    if (
        audit["n_evaluation_records"] < 1
        or audit["n_checked_records"]
        != audit["n_input_records"]
        - audit["excluded_evaluation_records"]
        + audit["n_reference_records"]
        or audit["n_evaluation_records"]
        > audit["n_input_records"] - audit["excluded_evaluation_records"]
    ):
        raise ValueError("Inconsistent design-audit population counts")
    findings = _object(audit.get("findings"), "design findings")
    if "training_reference_coverage" not in findings or set(findings) - CHECKS:
        raise ValueError("Unknown or missing design-audit checks")
    statuses = []
    incomplete = False
    for name, entry in findings.items():
        entry = _object(entry, "design finding")
        complete = entry.get("evidence_complete")
        count = entry.get("affected_records")
        if (
            type(complete) is not bool
            or count is not None
            and (type(count) is not int or not 0 <= count <= audit["n_checked_records"])
        ):
            raise ValueError("Invalid design finding count/evidence flag")
        _policy(entry.get("policy"), "design finding policy")
        expected = (
            "fail"
            if count and entry["policy"] == "forbid"
            else (
                "warn"
                if count and entry["policy"] == "warn"
                else "not_testable" if not complete else "pass"
            )
        )
        if entry.get("status") != expected or complete and count is None:
            raise ValueError("Inconsistent design finding status")
        statuses.append(expected)
        incomplete |= not complete
    coverage = (
        audit["training_reference_present"] and audit["reference_declared_complete"]
    )
    if findings["training_reference_coverage"][
        "evidence_complete"
    ] != coverage or audit["training_reference_present"] != (
        audit["n_reference_records"] > 0
    ):
        raise ValueError("Inconsistent reference coverage declaration")
    expected = (
        "fail"
        if "fail" in statuses
        else "not_testable" if incomplete else "warn" if "warn" in statuses else "pass"
    )
    if audit.get("status") != expected:
        raise ValueError("Inconsistent overall design-audit status")
    if audit.get("adapter") not in {None, "rdkit-molecule/v1"}:
        raise ValueError("Unsupported public design-audit adapter")
    return audit


def sanitize_design_audit(value: Any, policy: Mapping[str, Any]) -> dict[str, Any]:
    audit = validate_audit_summary(value)
    if audit["status"] == "withheld_small_audit_cells":
        return audit
    n = audit["n_checked_records"]
    counts = [
        audit["n_reference_records"],
        audit["excluded_evaluation_records"],
        *[
            entry["affected_records"]
            for entry in audit["findings"].values()
            if entry["affected_records"] is not None
        ],
    ]
    small = any(
        0 < count < policy["min_cell_size"] or 0 < n - count < policy["min_cell_size"]
        for count in counts
        if count <= n
    )
    excluded = audit["excluded_evaluation_records"]
    small |= bool(
        excluded
        and (
            excluded < policy["min_cell_size"]
            or audit["n_evaluation_records"] < policy["min_cell_size"]
        )
    )
    if small:
        return {
            "schema_version": AUDIT_SCHEMA,
            "status": "withheld_small_audit_cells",
            "scope": "provided_records_only",
            **({"model_role": audit["model_role"]} if audit.get("model_role") else {}),
        }
    output = {
        key: audit[key]
        for key in (
            "schema_version",
            "algorithm",
            "status",
            "definition_sha256",
            "training_reference_present",
            "reference_declared_complete",
            "scope",
            "n_evaluation_records",
            "n_input_records",
            "n_reference_records",
            "n_checked_records",
            "excluded_evaluation_records",
            "adapter",
        )
    }
    version = audit.get("adapter_version")
    if audit.get("model_role"):
        output["model_role"] = audit["model_role"]
    if version is not None:
        if not isinstance(version, str) or not re.fullmatch(
            r"[A-Za-z0-9_.+-]{1,64}", version
        ):
            raise ValueError("Invalid design adapter version")
        output["adapter_version"] = version
    output["findings"] = {
        name: {
            key: entry[key]
            for key in ("status", "affected_records", "evidence_complete", "policy")
        }
        for name, entry in audit["findings"].items()
    }
    output["limitations"] = LIMITATIONS
    return output


def render_design_audit(
    value: Mapping[str, Any], *, heading: str = "Evaluation-design audit"
) -> str:
    audit = validate_audit_summary(value)
    lines = [
        f"## {heading}",
        "",
        f"Status: **{audit['status']}**. Scope: provided records only.",
        "",
    ]
    if audit["status"] == "withheld_small_audit_cells":
        return "\n".join(lines)
    lines += [
        f"- Training reference present: {audit['training_reference_present']}",
        f"- Reference completeness declared by evaluator: {audit['reference_declared_complete']}",
        f"- Scored evaluation records: {audit['n_evaluation_records']}",
        f"- Rule-definition SHA-256: `{audit['definition_sha256']}`",
        "",
        "| Check | Status | Affected records | Evidence complete |",
        "| --- | --- | ---: | --- |",
    ]
    for name, finding in audit["findings"].items():
        count = (
            finding["affected_records"]
            if finding["affected_records"] is not None
            else "unavailable"
        )
        lines.append(
            f"| {name.replace('_', ' ')} | {finding['status']} | {count} | {finding['evidence_complete']} |"
        )
    lines += ["", *[f"- {item}" for item in LIMITATIONS], ""]
    return "\n".join(lines)
