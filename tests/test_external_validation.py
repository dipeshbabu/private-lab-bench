from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from privatelabbench.aggregate import aggregate_receipts
from privatelabbench.external_validation import (
    validate_profile,
    sanitize_validation,
    render_validation,
)
from privatelabbench.privacy.export import check_release
from privatelabbench.reports.receipt import verify_receipt
from privatelabbench.runner import run_config


def profile():
    return {
        "schema_version": "external-validation-profile/v1",
        "model": {
            "id": "synthetic-linear-model",
            "revision": "test-v1",
            "artifact_sha256": "f" * 64,
        },
        "dataset": {
            "visibility": "private",
            "training_overlap": "unknown",
            "site": "private institution",
            "collection_period": "2025-01 through 2025-12",
            "inclusion_criteria": "Synthetic observations; not a real researcher trial.",
        },
        "evaluator_relationship": "undisclosed",
        "relationship_statement": "Synthetic fixture only.",
    }


def config(tmp_path, name="run", *, context=None, release=None):
    output = tmp_path / name
    output.mkdir()
    path = output / "private.csv"
    pd.DataFrame(
        {
            "sample_id": [f"private-{i}" for i in range(24)],
            "target": [i + 0.125 for i in range(24)],
            "prediction": [i + 0.2 for i in range(24)],
            "baseline": [i + 1.2 for i in range(24)],
            "site": ["a"] * 12 + ["b"] * 12,
        }
    ).to_csv(path, index=False)
    settings = {
        "project": name,
        "protocol": "plb://generic/regression@1.0.0",
        "input": {
            "path": str(path),
            "target_column": "target",
            "prediction_column": "prediction",
            "baseline_prediction_column": "baseline",
            "sample_id_column": "sample_id",
            "slice_columns": ["site"],
        },
        "external_validation": context or profile(),
        "report": {
            "json": str(output / "run.json"),
            "markdown": str(output / "run.md"),
            "manifest": str(output / "run_manifest.json"),
        },
        "audit": {"path": str(output / "audit.jsonl")},
    }
    if release:
        settings["release"] = release
    source = output / "config.yaml"
    source.write_text(yaml.safe_dump(settings))
    return source, output, settings


def approval(context=None):
    context = context or profile()
    return {
        "schema_version": "release-policy/v1",
        "id": "synthetic-reviewed",
        "enabled": True,
        "require_privacy_audit": False,
        "include_protocol": True,
        "public_validation": {
            "model": context["model"],
            "dataset": {
                key: context["dataset"][key]
                for key in ("visibility", "training_overlap")
            },
            "evaluator_relationship": context["evaluator_relationship"],
        },
    }


def test_profile_reuses_evaluator_uncertainty_baseline_slices_and_binds_snapshot(
    tmp_path,
):
    source, output, settings = config(tmp_path)
    result = run_config(str(source))
    receipt = json.loads((output / "run_receipt.json").read_text())
    assert verify_receipt(output / "run_receipt.json")["valid"]
    evaluation = receipt["shareable"]["evaluation"]
    context = evaluation["external_validation"]
    assert (
        context["prediction_artifact_sha256"]
        == sha256(Path(settings["input"]["path"]).read_bytes()).hexdigest()
    )
    assert context["independence_verified"] is False
    assert evaluation["uncertainty"]["status"] == "evaluated"
    assert (
        receipt["local"]["baseline_metrics"]["rmse"] > result["clean_metrics"]["rmse"]
    )
    assert set(evaluation["slices"]["site"]) == {"a", "b"}
    assert not (output / "run_receipt.shareable.json").exists()


def test_default_export_omits_context_and_explicit_approval_releases_exact_subset(
    tmp_path,
):
    source, output, _ = config(tmp_path)
    run_config(str(source))
    local = json.loads((output / "run_receipt.json").read_text())
    policy = approval()
    default = {
        key: value for key, value in policy.items() if key != "public_validation"
    }
    _, public = check_release(
        local, default, evidence=local["local"]["release_evidence"]
    )
    assert "external_validation" not in public["shareable"]["evaluation"]
    decision, public = check_release(
        local, policy, evidence=local["local"]["release_evidence"]
    )
    assert decision.decision == "allow"
    text = json.dumps(public)
    assert (
        "private institution" not in text
        and "private-0" not in text
        and str(output) not in text
    )
    assert "collection_period" not in text and "prediction_artifact_sha256" not in text
    context = public["shareable"]["evaluation"]["external_validation"]
    assert context["model"] == profile()["model"]
    assert context["dataset"] == {
        "visibility": "private",
        "training_overlap": "unknown",
    }
    assert "undisclosed" in render_validation(context)
    policy["public_validation"]["model"]["revision"] = "wrong-revision"
    blocked, _ = check_release(
        local, policy, evidence=local["local"]["release_evidence"]
    )
    assert blocked.decision != "allow"


@pytest.mark.parametrize(
    "damage",
    ["digest", "path", "relationship", "visibility", "overlap", "unknown", "url"],
)
def test_invalid_profile_rejected(damage):
    value = profile()
    if damage == "digest":
        value["model"]["artifact_sha256"] = "mutable"
    elif damage == "path":
        value["model"]["id"] = "D:/private/model"
    elif damage == "relationship":
        value["evaluator_relationship"] = "verified_independent"
    elif damage == "visibility":
        value["dataset"]["visibility"] = "secret"
    elif damage == "overlap":
        value["dataset"]["training_overlap"] = "proven_no_overlap"
    elif damage == "unknown":
        value["dataset"]["rows"] = [1, 2]
    else:
        value["model"]["paper_url"] = "https://username:secret@example.com/paper"
    with pytest.raises(ValueError):
        validate_profile(value)


def test_missing_protocol_or_invalid_profile_fails_and_clears_previous_export(tmp_path):
    source, output, settings = config(tmp_path)
    public = output / "run_receipt.shareable.json"
    public.write_text("stale")
    del settings["protocol"]
    settings["task"] = "predictions"
    source.write_text(yaml.safe_dump(settings))
    with pytest.raises(ValueError, match="versioned"):
        run_config(str(source))
    assert not public.exists()


def test_aggregate_external_validations_checks_profile_model_and_artifact_digest(
    tmp_path,
):
    paths = []
    for name in ("a", "b"):
        source, output, _ = config(tmp_path, name, release=approval())
        run_config(str(source))
        paths.append(output / "run_receipt.shareable.json")
    model = {key: profile()["model"][key] for key in ("id", "revision")}
    artifact = aggregate_receipts(
        paths, models=[model], require_external_validation=True
    )
    assert len(artifact["shareable"]["models"][0]["sites"]) == 2
    with pytest.raises(ValueError, match="differs"):
        aggregate_receipts(
            paths,
            models=[{**model, "revision": "other"}],
            require_external_validation=True,
        )
    context = profile()
    context["model"]["artifact_sha256"] = "e" * 64
    source, output, _ = config(
        tmp_path, "c", context=context, release=approval(context)
    )
    run_config(str(source))
    with pytest.raises(ValueError, match="conflicting artifact digests"):
        aggregate_receipts(
            [paths[0], output / "run_receipt.shareable.json"],
            models=[model],
            require_external_validation=True,
        )


def test_renderer_escapes_declared_markup():
    value = {
        **profile(),
        "prediction_artifact_sha256": "d" * 64,
        "prediction_artifact_basis": "input_file_bytes",
    }
    value["dataset"]["site"] = "<script> [link](https://example.org)"
    text = render_validation(value)
    assert "<script>" not in text and "[link]" not in text


def test_schema_and_runnable_synthetic_walkthrough(tmp_path):
    from jsonschema import Draft202012Validator
    from scripts.external_validation_example import run
    from privatelabbench import external_validation

    schema = json.loads(
        (
            Path(external_validation.__file__).parent
            / "data/schemas/external-validation-profile-v1.schema.json"
        ).read_text()
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(profile())
    output = tmp_path / "walkthrough"
    run(output)
    assert verify_receipt(output / "run_receipt.shareable.json")["valid"]
    public = json.loads((output / "run_receipt.shareable.json").read_text())
    assert (
        public["shareable"]["evaluation"]["external_validation"]["model"][
            "artifact_sha256"
        ]
        == sha256((output / "model.json").read_bytes()).hexdigest()
    )
    assert (
        "Synthetic"
        in public["shareable"]["evaluation"]["external_validation"]["dataset"][
            "provenance_statement"
        ]
    )


def test_unapproved_model_citation_is_not_copied(tmp_path):
    context = profile()
    context["model"]["citation"] = "Private citation notes; not approved."
    source, output, _ = config(tmp_path, context=context, release=approval())
    run_config(str(source))
    public = (output / "run_receipt.shareable.json").read_text()
    assert "Private citation notes" not in public


def test_release_and_summary_schemas_resolve_packaged_definitions(tmp_path):
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    from privatelabbench import external_validation

    directory = Path(external_validation.__file__).parent / "data/schemas"
    resources = []
    for path in directory.glob("*.schema.json"):
        value = json.loads(path.read_text())
        resource = Resource.from_contents(value)
        resources.append((path.name, resource))
        if "$id" in value:
            resources.append((value["$id"], resource))
    registry = Registry().with_resources(resources)
    policy_schema = json.loads(
        (directory / "release-policy-v1.schema.json").read_text()
    )
    Draft202012Validator(policy_schema, registry=registry).validate(approval())
    source, output, _ = config(tmp_path, release=approval())
    run_config(str(source))
    receipt = json.loads((output / "run_receipt.shareable.json").read_text())
    schema = json.loads((directory / "external-validation-v1.schema.json").read_text())
    Draft202012Validator(schema, registry=registry).validate(
        receipt["shareable"]["evaluation"]["external_validation"]
    )
