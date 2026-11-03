from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from privatelabbench.cli import main
from privatelabbench.hidden_benchmarks import (
    load_benchmark_spec,
    prepare_submission,
    evaluate_benchmark,
    benchmark_template,
)
from privatelabbench.leaderboards import build_leaderboard, rank_rows
from privatelabbench.privacy.export import check_release
from privatelabbench.protocols import (
    EvaluationProtocol,
    apply_protocol,
    resolve_protocol,
)
from privatelabbench.reports.integrity import verify_payload


@pytest.fixture
def owner(tmp_path):
    rules = resolve_protocol("plb://generic/regression@1.0.0").as_dict()
    rules["id"] = "plb://test/hidden-regression"
    rules["uncertainty"]["resamples"] = 100
    rules["comparison"]["resamples"] = 100
    rules["ranking"] = {
        "metric": "mae",
        "rule": "conservative_interval_ties",
        "practical_tie_tolerance": 0.02,
        "require_uncertainty": True,
    }
    definition = EvaluationProtocol.from_dict(rules)
    protocol = tmp_path / "protocol.yaml"
    protocol.write_text(yaml.safe_dump(rules))
    private = tmp_path / "owner-labels.csv"
    frame = pd.DataFrame(
        {
            "owner_id": [f"hidden-{i:04d}" for i in range(40)],
            "hidden_label": [i + 0.125 for i in range(40)],
        }
    )
    frame.to_csv(private, index=False)
    benchmark = {
        "id": "synthetic-hidden",
        "version": "1.0.0",
        "suite": "owner-hidden-benchmark",
        "protocol": "prediction-table/v1",
    }
    models = [
        {"id": name, "revision": "v1"} for name in ("model-a", "model-b", "model-c")
    ]
    policy = {
        "schema_version": "release-policy/v1",
        "id": "owner-reviewed",
        "enabled": True,
        "require_privacy_audit": False,
        "include_protocol": True,
        "include_submission": True,
        "public_models": models,
        "public_submission_ids": ["sub-a", "sub-b", "sub-c"],
        "public_benchmark": benchmark,
    }
    spec = {
        "schema_version": "hidden-benchmark/v1",
        "id": benchmark["id"],
        "version": benchmark["version"],
        "protocol": "protocol.yaml",
        "protocol_sha256": definition.sha256,
        "input_access": "approved_participant_inputs",
        "private_input": {
            "path": str(private),
            "sample_id_column": "owner_id",
            "target_column": "hidden_label",
            "slice_columns": [],
        },
        "submission": {
            "sample_id_column": "sample_id",
            "prediction_column": "prediction",
        },
        "release": policy,
    }
    path = tmp_path / "benchmark.yaml"
    path.write_text(yaml.safe_dump(spec))
    predictions = []
    for index, error in enumerate((0.1, 0.11, 0.8)):
        source = tmp_path / f"model-{index}.csv"
        pd.DataFrame(
            {
                "sample_id": frame.owner_id,
                "prediction": frame.hidden_label + error + np.sin(np.arange(40)) * 0.01,
            }
        ).sample(frac=1, random_state=13).to_csv(source, index=False)
        predictions.append(source)
    return {
        "root": tmp_path,
        "spec_path": path,
        "spec": spec,
        "protocol_path": protocol,
        "definition": definition,
        "private": private,
        "frame": frame,
        "predictions": predictions,
        "policy": policy,
        "models": models,
    }


def evaluate(owner, index=0, **options):
    return evaluate_benchmark(
        owner["spec_path"],
        owner["predictions"][index],
        owner["root"] / f"result-{index}",
        submission_id=f"sub-{chr(97+index)}",
        model=owner["models"][index],
        **options,
    )


def test_owner_alignment_template_and_public_receipt_never_include_targets_or_ids(
    owner,
):
    template = owner["root"] / "template.csv"
    benchmark_template(owner["spec_path"], template)
    assert list(pd.read_csv(template)) == ["sample_id", "prediction"]
    benchmark = load_benchmark_spec(owner["spec_path"])
    frame, identity, provenance = prepare_submission(
        benchmark,
        owner["predictions"][0],
        submission_id="sub-a",
        model=owner["models"][0],
    )
    assert list(frame.sample_id) == list(owner["frame"].owner_id)
    np.testing.assert_allclose(frame.target, owner["frame"].hidden_label)
    assert (
        identity["artifact_sha256"]
        == sha256(owner["predictions"][0].read_bytes()).hexdigest()
    )
    evaluate(owner)
    receipt = owner["root"] / "result-0/evaluation_receipt.shareable.json"
    payload = json.loads(receipt.read_text())
    assert verify_payload(payload)["valid"]
    text = receipt.read_text() + (receipt.parent / "evaluation_receipt.md").read_text()
    assert (
        "hidden-0000" not in text
        and "hidden_label" not in text
        and str(owner["private"]) not in text
    )
    assert "owner_input_sha256" not in text and "39.125" not in text
    assert payload["shareable"]["evaluation"]["benchmark_submission"]["id"] == "sub-a"
    assert (
        payload["shareable"]["evaluation"]["protocol"] == owner["definition"].identity()
    )


@pytest.mark.parametrize(
    "damage", ["missing", "duplicate", "unknown", "target", "feature", "nonfinite"]
)
def test_invalid_submission_rejected_without_public_result(owner, damage):
    path = owner["predictions"][0]
    frame = pd.read_csv(path)
    if damage == "missing":
        frame = frame.iloc[:-1]
    elif damage == "duplicate":
        frame.loc[1, "sample_id"] = frame.loc[0, "sample_id"]
    elif damage == "unknown":
        frame.loc[0, "sample_id"] = "unknown-private-record"
    elif damage == "target":
        frame["target"] = 0
    elif damage == "feature":
        frame["private_feature"] = 1
    else:
        frame.loc[0, "prediction"] = np.inf
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError):
        evaluate(owner)
    assert not (owner["root"] / "result-0/evaluation_receipt.shareable.json").exists()


def test_unapproved_submission_metadata_stays_local(owner):
    manifest = owner["root"] / "submission.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": "submission-manifest/v1",
                "id": "sub-a",
                "model": owner["models"][0],
                "prediction_sha256": sha256(
                    owner["predictions"][0].read_bytes()
                ).hexdigest(),
                "participant": "PRIVATE_PARTICIPANT_NOTE",
                "citation": "PRIVATE_CITATION_NOTE",
            }
        )
    )
    evaluate(owner, submission_manifest=manifest)
    local = (owner["root"] / "result-0/benchmark_input.json").read_text()
    public = (owner["root"] / "result-0/evaluation_receipt.shareable.json").read_text()
    assert (
        "PRIVATE_PARTICIPANT_NOTE" in local
        and "PRIVATE_PARTICIPANT_NOTE" not in public
        and "PRIVATE_CITATION_NOTE" not in public
    )


def test_owner_only_inputs_reject_participant_mode_and_templates(owner):
    owner["spec"]["input_access"] = "owner_only"
    owner["spec_path"].write_text(yaml.safe_dump(owner["spec"]))
    with pytest.raises(ValueError, match="Owner-only"):
        evaluate(owner)
    with pytest.raises(ValueError):
        benchmark_template(owner["spec_path"], owner["root"] / "template.csv")


def test_owner_only_accepts_snapshot_bound_trusted_scoring_provenance(owner):
    from privatelabbench.scoring import score_local

    example = Path(__file__).resolve().parents[1] / "examples/trusted_scoring"
    scored = score_local(
        example / "manifest.yaml",
        example / "inputs.csv",
        owner["root"] / "scored.csv",
        data_units={"molecular_weight": "g/mol", "logp": "dimensionless"},
        dataset_version="synthetic-v1",
    )
    raw = pd.read_csv(example / "inputs.csv")
    raw[["sample_id", "target"]].rename(
        columns={"sample_id": "owner_id", "target": "hidden_label"}
    ).to_csv(owner["private"], index=False)
    spec = owner["spec"]
    spec["input_access"] = "owner_only"
    model = {key: scored["model"][key] for key in ("id", "revision")}
    spec["release"]["public_models"] = [model]
    owner["spec_path"].write_text(yaml.safe_dump(spec))
    evaluate_benchmark(
        owner["spec_path"],
        scored["predictions"],
        owner["root"] / "trusted",
        submission_id="sub-a",
        model=model,
        scoring_provenance=scored["provenance"],
    )
    receipt = json.loads(
        (owner["root"] / "trusted/evaluation_receipt.shareable.json").read_text()
    )
    assert (
        receipt["shareable"]["evaluation"]["benchmark_submission"]["submission_kind"]
        == "owner_scored_predictions"
    )


def test_ranking_uses_explicit_protocol_and_conservative_ties(owner):
    paths = []
    for index in range(3):
        evaluate(owner, index)
        paths.append(
            owner["root"] / f"result-{index}/evaluation_receipt.shareable.json"
        )
    artifact = build_leaderboard(paths, owner["protocol_path"])
    rows = artifact["shareable"]["rows"]
    assert [row["rank_group"] for row in rows] == [1, 1, 2]
    assert artifact["shareable"]["ranking_status"] == "conservative_interval_groups"
    assert verify_payload(artifact)["valid"]
    decision, public = check_release(artifact, owner["policy"])
    assert decision.decision == "allow"
    assert "hidden_label" not in json.dumps(public) and "hidden-0000" not in json.dumps(
        public
    )
    artifact["shareable"]["rows"][0]["rank_group"] = 999
    assert (
        check_release(artifact, owner["policy"])[1]["shareable"]["rows"][0][
            "rank_group"
        ]
        == 1
    )


def test_no_ranking_without_protocol_rule_and_no_false_precision(owner):
    rule = owner["definition"].as_dict()["ranking"]
    rows = [
        {
            "submission": {
                "id": f"s-{index}",
                "model": {"id": f"m-{index}", "revision": "v1"},
            },
            "estimate": point,
            "interval": interval,
        }
        for index, (point, interval) in enumerate(
            [(0.2, {"lower": 0.1, "upper": 0.3}), (0.4, None)]
        )
    ]
    assert rank_rows(rows, None, "mae")[1] == "not_declared_in_protocol"
    ranked, status = rank_rows(rows, rule, "mae")
    assert status == "uncertainty_unavailable" and all(
        row["rank_group"] is None for row in ranked
    )


def test_protocol_ranking_changes_digest_and_audit_floors_cannot_be_waived(owner):
    rules = owner["definition"].as_dict()
    old = owner["definition"].sha256
    rules["ranking"]["practical_tie_tolerance"] = 0.03
    assert EvaluationProtocol.from_dict(rules).sha256 != old
    rules["release"]["require_design_audit"] = True
    definition = EvaluationProtocol.from_dict(rules)
    with pytest.raises(ValueError, match="weaken"):
        apply_protocol({"release": {"require_design_audit": False}}, definition)
    assert (
        resolve_protocol("plb://generic/regression@1.0.0").sha256
        == "d1c29e51956bdc9e4e6637cd6f6ee387a7bfc233c842312c267ba5c229e414a5"
    )


def test_cli_failures_hide_private_target_values_and_clear_stale_public(
    owner, monkeypatch, capsys
):
    evaluate(owner)
    public = owner["root"] / "result-0/evaluation_receipt.shareable.json"
    assert public.exists()
    owner["spec"]["protocol_sha256"] = "a" * 64
    owner["spec_path"].write_text(yaml.safe_dump(owner["spec"]))
    monkeypatch.setattr(
        "sys.argv",
        [
            "plb",
            "benchmark-evaluate",
            str(owner["spec_path"]),
            str(owner["predictions"][0]),
            "--submission-id",
            "sub-a",
            "--model",
            "model-a@v1",
            "--output-dir",
            str(owner["root"] / "result-0"),
        ],
    )
    assert main() == 2
    assert not public.exists()
    assert "hidden-0000" not in capsys.readouterr().out


@pytest.mark.parametrize("multiclass", [False, True])
def test_classification_probabilities_and_explicit_label_strings(owner, multiclass):
    rules = resolve_protocol("plb://generic/binary@1.0.1").as_dict()
    labels = ["a", "b", "c"] if multiclass else ["01", "02"]
    rules["id"] = (
        "plb://test/hidden-multiclass" if multiclass else "plb://test/hidden-binary"
    )
    rules["task_type"] = "multiclass" if multiclass else "classification"
    rules["input_schema"]["class_labels"] = labels
    rules["metrics"] = (
        ["accuracy", "macro_f1", "weighted_f1", "log_loss", "macro_auroc_ovr"]
        if multiclass
        else ["accuracy", "f1", "auroc"]
    )
    rules["primary_metric"] = "macro_auroc_ovr" if multiclass else "auroc"
    rules["comparison"]["metric"] = rules["primary_metric"]
    rules["uncertainty"]["resamples"] = 100
    rules["comparison"]["resamples"] = 100
    definition = EvaluationProtocol.from_dict(rules)
    owner["protocol_path"].write_text(yaml.safe_dump(rules))
    owner["spec"]["protocol_sha256"] = definition.sha256
    frame = owner["frame"].copy()
    classes = np.arange(len(frame)) % len(labels)
    frame["hidden_label"] = [labels[index] for index in classes]
    frame.to_csv(owner["private"], index=False)
    predictions = pd.DataFrame({"sample_id": frame.owner_id})
    if multiclass:
        columns = ["score_a", "score_b", "score_c"]
        owner["spec"]["submission"] = {
            "sample_id_column": "sample_id",
            "prediction_columns": columns,
        }
        values = np.eye(3)[classes] * 0.85 + 0.05
        for index, name in enumerate(columns):
            predictions[name] = values[:, index]
    else:
        predictions["prediction"] = np.where(classes == 1, 0.9, 0.1)
    predictions.to_csv(owner["predictions"][0], index=False)
    owner["spec_path"].write_text(yaml.safe_dump(owner["spec"]))
    evaluate(owner)
    payload = json.loads(
        (owner["root"] / "result-0/evaluation_receipt.shareable.json").read_text()
    )
    assert payload["shareable"]["evaluation"]["metrics"][
        rules["primary_metric"]
    ] == pytest.approx(1.0)


def test_cli_does_not_echo_invalid_hidden_target_values(owner, monkeypatch, capsys):
    frame = owner["frame"].copy()
    frame["hidden_label"] = frame.hidden_label.astype(object)
    frame.loc[0, "hidden_label"] = "PRIVATE_INVALID_TARGET_SENTINEL"
    frame.to_csv(owner["private"], index=False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "plb",
            "benchmark-evaluate",
            str(owner["spec_path"]),
            str(owner["predictions"][0]),
            "--submission-id",
            "sub-a",
            "--model",
            "model-a@v1",
            "--output-dir",
            str(owner["root"] / "invalid-label"),
        ],
    )
    assert main() == 2
    assert "PRIVATE_INVALID_TARGET_SENTINEL" not in capsys.readouterr().out
    assert not (
        owner["root"] / "invalid-label/evaluation_receipt.shareable.json"
    ).exists()


def test_leaderboard_rejects_duplicate_receipts_and_requires_full_ranking_definition(
    owner,
):
    evaluate(owner)
    path = owner["root"] / "result-0/evaluation_receipt.shareable.json"
    with pytest.raises(ValueError, match="Duplicate"):
        build_leaderboard([path, path], owner["protocol_path"])
    artifact = build_leaderboard([path], owner["protocol_path"])
    artifact["shareable"]["ranking_rules"]["practical_tie_tolerance"] = 999
    assert check_release(artifact, owner["policy"])[1] is None


def test_owner_and_submission_sources_are_preserved(owner):
    before = owner["private"].read_bytes()
    with pytest.raises(ValueError):
        evaluate_benchmark(
            owner["spec_path"],
            owner["predictions"][0],
            owner["private"].parent,
            submission_id="sub-a",
            model=owner["models"][0],
        )
    assert owner["private"].read_bytes() == before
    with pytest.raises(ValueError):
        benchmark_template(owner["spec_path"], owner["private"])


def test_schema_definitions_cover_actual_owner_receipts_and_leaderboards(owner):
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    import privatelabbench.hidden_benchmarks as module
    from privatelabbench.reports.integrity import attach_integrity_metadata

    directory = Path(module.__file__).parent / "data/schemas"
    resources = []
    for path in directory.glob("*.schema.json"):
        data = json.loads(path.read_text())
        resource = Resource.from_contents(data)
        resources.append((path.name, resource))
        if "$id" in data:
            resources.append((data["$id"], resource))
    registry = Registry().with_resources(resources)

    def validate(filename, data):
        schema = json.loads((directory / filename).read_text())
        Draft202012Validator(schema, registry=registry).validate(data)

    validate("hidden-benchmark-v1.schema.json", owner["spec"])
    evaluate(owner)
    path = owner["root"] / "result-0/evaluation_receipt.shareable.json"
    receipt = json.loads(path.read_text())
    validate(
        "benchmark-submission-v1.schema.json",
        receipt["shareable"]["evaluation"]["benchmark_submission"],
    )
    artifact = build_leaderboard([path], owner["protocol_path"])
    validate("benchmark-leaderboard-v1.schema.json", artifact)
    decision, public = check_release(artifact, owner["policy"])
    assert decision.decision == "allow"
    validate("benchmark-leaderboard-v1.schema.json", attach_integrity_metadata(public))
    validate("release-policy-v1.schema.json", owner["policy"])
    with pytest.raises(ValueError):
        build_leaderboard([path], owner["protocol_path"], require_trusted_signer=True)


def test_runnable_synthetic_owner_walkthrough(tmp_path):
    from scripts.hidden_benchmark_example import run

    result = run(tmp_path / "walkthrough")
    assert verify_payload(result)["valid"]
    text = json.dumps(result)
    assert "synthetic-0000" not in text and "owner_input_sha256" not in text
    assert len(result["shareable"]["rows"]) == 2


def test_leaderboard_cli_uses_only_verified_receipts_and_clears_failed_export(
    owner, monkeypatch
):
    evaluate(owner)
    path = owner["root"] / "result-0/evaluation_receipt.shareable.json"
    policy = owner["root"] / "leaderboard-release.yaml"
    policy.write_text(yaml.safe_dump(owner["policy"]))
    output = owner["root"] / "leaderboard.json"
    args = [
        "plb",
        "benchmark-leaderboard",
        str(path),
        "--protocol",
        str(owner["protocol_path"]),
        "--release-policy",
        str(policy),
        "--out",
        str(output),
    ]
    monkeypatch.setattr("sys.argv", args)
    assert main() == 0
    public = owner["root"] / "leaderboard.shareable.json"
    assert public.exists() and verify_payload(json.loads(public.read_text()))["valid"]
    path.write_text("invalid JSON")
    assert main() == 2
    assert not public.exists() and not output.with_suffix(".md").exists()


def test_ordered_label_codes_remain_consistent_for_baselines_profiles_and_pairs(
    tmp_path,
):
    from privatelabbench.runner import run_config
    from privatelabbench.eval.paired_comparison import (
        compare_prediction_tables,
        PairedComparisonConfig,
    )

    table = tmp_path / "label-codes.csv"
    labels = ["02", "01"] * 20
    values = np.array([0.9 if label == "01" else 0.1 for label in labels])
    pd.DataFrame(
        {
            "sample_id": [f"s-{index}" for index in range(40)],
            "target": labels,
            "prediction": values,
            "baseline": values,
        }
    ).to_csv(table, index=False)
    rules = resolve_protocol("plb://generic/binary@1.0.1").as_dict()
    rules["id"] = "plb://test/ordered-codes"
    rules["input_schema"]["class_labels"] = ["02", "01"]
    rules["uncertainty"]["resamples"] = 100
    rules["comparison"]["resamples"] = 100
    protocol = tmp_path / "codes.yaml"
    protocol.write_text(yaml.safe_dump(rules))
    for profile in (False, True):
        name = "profile" if profile else "ordinary"
        output = tmp_path / name
        settings = {
            "project": name,
            "protocol": str(protocol),
            "input": {
                "path": str(table),
                "sample_id_column": "sample_id",
                "target_column": "target",
                "prediction_column": "prediction",
                "baseline_prediction_column": "baseline",
            },
            "report": {
                "json": str(output / "run.json"),
                "markdown": str(output / "run.md"),
                "manifest": str(output / "run_manifest.json"),
            },
            "audit": {"path": str(output / "audit.jsonl")},
        }
        if profile:
            settings["external_validation"] = {
                "schema_version": "external-validation-profile/v1",
                "model": {
                    "id": "synthetic",
                    "revision": "v1",
                    "artifact_sha256": "f" * 64,
                },
                "dataset": {"visibility": "private", "training_overlap": "unknown"},
                "evaluator_relationship": "undisclosed",
            }
        config = tmp_path / f"{name}.yaml"
        config.write_text(yaml.safe_dump(settings))
        result = run_config(str(config))
        assert (
            result["clean_metrics"]["auroc"] == 1.0
            and result["baseline_metrics"]["auroc"] == 1.0
        )
    paired = compare_prediction_tables(
        str(table),
        str(table),
        target="target",
        task_type="classification",
        class_labels=["02", "01"],
        config=PairedComparisonConfig(metric="auroc", resamples=100, permutations=0),
    )
    assert paired["model_a"]["metrics"]["auroc"] == 1.0
