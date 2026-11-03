"""Declared external-validation context around the ordinary prediction evaluator."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import re
from typing import Any, Mapping
from urllib.parse import urlsplit

import pandas as pd

SCHEMA = "external-validation/v1"
PROFILE_SCHEMA = "external-validation-profile/v1"
RELATIONSHIPS = {"independent", "affiliated", "model_developer", "undisclosed"}
VISIBILITY = {"public", "private", "restricted", "undisclosed"}
OVERLAP = {"none_known", "known", "unknown", "not_assessed"}
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@+-]{0,127}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _object(value: Any, required: set[str], optional: set[str], label: str) -> dict:
    if (
        not isinstance(value, Mapping)
        or not required <= set(value)
        or set(value) - required - optional
    ):
        raise ValueError(f"Invalid {label} fields")
    return deepcopy(dict(value))


def _text(value: Any, label: str, *, maximum: int = 1200) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError(f"{label} must be bounded, single-line text")
    return value


def model_metadata(value: Any) -> dict:
    model = _object(
        value,
        {"id", "revision", "artifact_sha256"},
        {"paper_url", "citation"},
        "model identity",
    )
    for key in ("id", "revision"):
        if not isinstance(model[key], str) or not TOKEN.fullmatch(model[key]):
            raise ValueError(
                "Model ID/revision must be stable short labels; keep paths local"
            )
    if not isinstance(model["artifact_sha256"], str) or not DIGEST.fullmatch(
        model["artifact_sha256"]
    ):
        raise ValueError("Model artifact_sha256 must identify an immutable artifact")
    if "paper_url" in model:
        url = urlsplit(_text(model["paper_url"], "paper_url", maximum=500))
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "Paper references require an HTTPS URL without credentials, query, or fragment"
            )
    if "citation" in model:
        _text(model["citation"], "citation")
    return model


def validate_profile(value: Any) -> dict:
    profile = _object(
        value,
        {"schema_version", "model", "dataset", "evaluator_relationship"},
        {"relationship_statement"},
        "external-validation profile",
    )
    if (
        profile["schema_version"] != PROFILE_SCHEMA
        or profile["evaluator_relationship"] not in RELATIONSHIPS
    ):
        raise ValueError(
            "Unsupported external-validation profile or evaluator relationship"
        )
    profile["model"] = model_metadata(profile["model"])
    dataset = _object(
        profile["dataset"],
        {"visibility", "training_overlap"},
        {"site", "collection_period", "inclusion_criteria", "provenance_statement"},
        "dataset provenance",
    )
    if (
        dataset["visibility"] not in VISIBILITY
        or dataset["training_overlap"] not in OVERLAP
    ):
        raise ValueError(
            "Declare dataset visibility and known/unknown model-training overlap"
        )
    for key in set(dataset) - {"visibility", "training_overlap"}:
        _text(dataset[key], key)
    if "relationship_statement" in profile:
        _text(profile["relationship_statement"], "relationship_statement")
    profile["dataset"] = dataset
    return profile


def prepare_validation(config, path):
    """Return the exact frame scored and its declared local context; never train."""
    if config.protocol is None or config.task_id not in {"predictions", "tabular"}:
        raise ValueError(
            "External validation requires a versioned prediction-table evaluation protocol"
        )
    profile = validate_profile(config.raw["external_validation"])
    if config.prepared_input is None:
        from pathlib import Path
        from privatelabbench.eval.sampling import sampling_design

        content = Path(path).read_bytes()
        inputs = config.raw["input"]
        sample = inputs.get("sample_id_column", "sample_id")
        design = sampling_design(config.raw.get("sampling_design"))
        dtype = {
            **({sample: "string"} if sample else {}),
            **(
                {column: "string" for column in design.metadata_columns}
                if design
                else {}
            ),
        }
        if inputs.get("class_labels"):
            dtype[inputs["target_column"]] = "string"
        group=config.protocol.as_dict().get("evaluation_group")
        if group: dtype[group["column"]]="string"
        frame = pd.read_csv(BytesIO(content), dtype=dtype)
        basis = "input_file_bytes"
    else:
        frame = config.prepared_input
        content = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
        basis = "audited_frame_csv"
    scoring = config.raw.get("scoring_provenance")
    if scoring is not None:
        source_digest = (
            sha256(content).hexdigest()
            if basis == "input_file_bytes"
            else config.design_audits[0]["artifact"]["local"]["evaluation_sha256"]
        )
        if (
            not isinstance(scoring, Mapping)
            or scoring.get("schema_version") != "local-scoring-provenance/v1"
            or scoring.get("scope") != "local"
            or scoring.get("model") != profile["model"]
            or scoring.get("prediction_sha256") != source_digest
        ):
            raise ValueError(
                "Scored prediction snapshot or model identity differs from local scoring provenance"
            )
    return frame, {
        "schema_version": SCHEMA,
        "model": profile["model"],
        "dataset": profile["dataset"],
        "evaluator_relationship": profile["evaluator_relationship"],
        "relationship_statement": profile.get("relationship_statement"),
        "prediction_artifact_sha256": sha256(content).hexdigest(),
        "prediction_artifact_basis": basis,
        "claim_scope": "declared_external_evaluation",
        "independence_verified": False,
    }


def public_approval(value: Any) -> dict:
    """Exact reviewed values, rather than permission to copy arbitrary metadata."""
    approved = _object(
        value,
        {"model", "dataset", "evaluator_relationship"},
        {"prediction_artifact_sha256", "prediction_artifact_basis"},
        "public external-validation approval",
    )
    model_metadata(approved["model"])
    validate_profile(
        {
            "schema_version": PROFILE_SCHEMA,
            **{
                key: approved[key]
                for key in ("model", "dataset", "evaluator_relationship")
            },
        }
    )
    if "prediction_artifact_sha256" in approved:
        if not DIGEST.fullmatch(
            str(approved["prediction_artifact_sha256"])
        ) or approved.get("prediction_artifact_basis") not in {
            "input_file_bytes",
            "audited_frame_csv",
        }:
            raise ValueError(
                "Approve the exact prediction digest and its basis together"
            )
    elif "prediction_artifact_basis" in approved:
        raise ValueError("Prediction basis requires its exact approved digest")
    return approved


def sanitize_validation(value: Any, approval: Any) -> dict:
    source = dict(value) if isinstance(value, Mapping) else {}
    approved = public_approval(approval)
    if source.get("schema_version") != SCHEMA:
        raise ValueError("Missing external-validation evidence")
    for key, item in approved.items():
        actual = source.get(key)
        if key in {"dataset", "model"}:
            if not isinstance(actual, Mapping) or any(
                actual.get(field) != content for field, content in item.items()
            ):
                raise ValueError(
                    "Public dataset declarations differ from the evaluated profile"
                )
        elif actual != item:
            raise ValueError(
                "Public validation identity differs from the evaluated profile"
            )
    return {
        "schema_version": SCHEMA,
        **approved,
        "claim_scope": "declared_external_evaluation",
        "independence_verified": False,
    }


def render_validation(value: Mapping[str, Any]) -> str:
    # Escape user declarations so the Markdown summary cannot introduce links/HTML.
    from html import escape

    def plain(item):
        return (
            escape(str(item))
            .replace("`", "&#96;")
            .replace("[", "&#91;")
            .replace("]", "&#93;")
        )

    model, dataset = value["model"], value["dataset"]
    lines = [
        "## External validation",
        "",
        f"Model: {plain(model['id'])}@{plain(model['revision'])}",
        f"Model artifact SHA-256: {model['artifact_sha256']}",
        f"Evaluator relationship (declared): {plain(value['evaluator_relationship'])}",
        f"Dataset visibility: {plain(dataset['visibility'])}; training overlap: {plain(dataset['training_overlap'])}.",
    ]
    for key in (
        "site",
        "collection_period",
        "inclusion_criteria",
        "provenance_statement",
    ):
        if key in dataset:
            lines.append(f"{key.replace('_', ' ').capitalize()}: {plain(dataset[key])}")
    for key in ("paper_url", "citation"):
        if key in model:
            lines.append(f"Model {key}: {plain(model[key])}")
    if value.get("prediction_artifact_sha256"):
        lines.append(
            f"Prediction artifact SHA-256 ({value['prediction_artifact_basis']}): {value['prediction_artifact_sha256']}"
        )
    lines.extend(
        [
            "",
            "These provenance and relationship statements are evaluator declarations. Artifact integrity does not verify dataset truth, independence, or prospective/clinical/regulatory validity.",
        ]
    )
    return "\n\n".join(lines) + "\n"
