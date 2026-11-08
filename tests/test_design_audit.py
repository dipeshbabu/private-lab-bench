import json
from pathlib import Path

import pandas as pd
import pytest

from privatelabbench.design_audit import EvaluationDesign, prepare_evaluation
from privatelabbench.reports.integrity import verify_payload


def run_table(tmp_path, name, error=0.1):
    rows = [
        {
            "sample_id": f"train-{i}",
            "split": "train",
            "target": i + 0.23,
            "prediction": i + 10.23,
            "baseline": i + 20.23,
            "qc": None,
        }
        for i in range(10)
    ]
    rows += [
        {
            "sample_id": f"{name}-protected-{i}",
            "split": "test",
            "target": i + 0.23,
            "prediction": i + 0.23 + error,
            "baseline": i + 0.53,
            "qc": True,
        }
        for i in range(20)
    ]
    rows += [
        {
            "sample_id": f"{name}-excluded-{i}",
            "split": "test",
            "target": None,
            "prediction": None,
            "baseline": None,
            "qc": False,
        }
        for i in range(5)
    ]
    return csv(tmp_path, name, rows)


def run_rules():
    return definition(
        split_column="split",
        exclusions=[{"column": "qc", "operator": "equals", "value": False}],
    )


def invoke(monkeypatch, args):
    from privatelabbench.cli import main

    monkeypatch.setattr("sys.argv", ["plb", *map(str, args)])
    return main()


def release_policy():
    return {
        "schema_version": "release-policy/v1",
        "id": "reviewed-audited-synthetic",
        "enabled": True,
        "min_samples": 20,
        "min_cell_size": 5,
        "require_privacy_audit": False,
        "require_design_audit": True,
        "include_design_audit": True,
    }


def definition(**kwargs):
    return EvaluationDesign.from_dict(
        {"schema_version": "evaluation-design/v1", **kwargs}
    )


@pytest.mark.parametrize(
    "rules",
    [
        {"schema_version": "unknown"},
        {"sample_id_column": None},
        {"entity_columns": ["patient", "patient"]},
        {"group_columns": [""]},
        {"evaluation_partition": "training"},
        {"reference_partition": "test"},
        {
            "partition_labels": {
                "train": ["same"],
                "validation": ["valid"],
                "test": ["same"],
            }
        },
        {"forbidden_pairs": [["train", "test"], ["test", "train"]]},
        {"forbidden_pairs": [["train", "train"]]},
        {"overlap": {"unknown": "forbid"}},
        {"overlap": {"entities": "ignore"}},
        {"label_tolerance": float("nan")},
        {"chronology": {"column": "date", "timezone": "local"}},
        {"chronology": {"column": "date", "strictly_before": 1}},
        {"chronology": {"column": "date", "cutoff": "01/02/2026"}},
        {
            "exclusions": [
                {"column": "sample_id", "operator": "equals", "value": "patient-1"}
            ]
        },
        {"exclusions": [{"column": "qc", "operator": "equals", "value": ["a", "b"]}]},
        {"exclusions": [{"column": "qc", "operator": "is_missing", "value": 1}]},
        {"exclusions": [{"column": "qc", "operator": "less_than", "value": True}]},
        {
            "adapter": {
                "name": "rdkit-molecule/v1",
                "smiles_column": "smiles",
                "canonical_isomeric": "yes",
            }
        },
        {
            "adapter": {
                "name": "rdkit-molecule/v1",
                "smiles_column": "smiles",
                "near_duplicates": {"threshold": 0},
            }
        },
        {
            "adapter": {
                "name": "rdkit-molecule/v1",
                "smiles_column": "smiles",
                "near_duplicates": {"max_pairs": False},
            }
        },
    ],
)
def test_ambiguous_or_unsafe_design_declarations_are_rejected_before_reading_data(
    rules,
):
    with pytest.raises(ValueError):
        definition(**rules)


def csv(tmp_path, name, rows):
    path = tmp_path / f"{name}.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return str(path)


def test_missing_or_partial_training_reference_is_never_a_negative_contamination_claim(
    tmp_path,
):
    evaluation = csv(
        tmp_path,
        "evaluation",
        [{"sample_id": "private-e1"}, {"sample_id": "private-e2"}],
    )
    for reference in (
        None,
        csv(tmp_path, "partial-training", [{"sample_id": "private-t1"}]),
    ):
        audit = prepare_evaluation(
            evaluation, definition(), training_reference=reference
        ).artifact
        assert audit["audit"]["status"] == "not_testable"
        assert (
            audit["audit"]["findings"]["training_reference_coverage"]["status"]
            == "not_testable"
        )
        assert verify_payload(audit)["valid"]
        assert "no_leakage" not in json.dumps(audit)


def test_exact_sample_id_overlap_fails_even_with_an_incomplete_reference(tmp_path):
    evaluation = csv(
        tmp_path,
        "evaluation",
        [{"sample_id": "private-e1"}, {"sample_id": "private-e2"}],
    )
    reference = csv(
        tmp_path, "training", [{"sample_id": "private-t1"}, {"sample_id": "private-e2"}]
    )
    for complete in (False, True):
        result = prepare_evaluation(
            evaluation,
            definition(),
            training_reference=reference,
            reference_complete=complete,
        ).artifact
        assert result["audit"]["status"] == "fail"
        assert result["audit"]["findings"]["sample_id_overlap"]["affected_records"] == 2
        assert result["local"]["examples"]["sample_id_overlap"] == [
            "private-e2",
            "private-e2",
        ]


def test_duplicate_entities_and_groups_are_checked_independently_of_row_ids(tmp_path):
    evaluation = csv(
        tmp_path,
        "evaluation",
        [
            {
                "sample_id": "e1",
                "compound": "protected-compound",
                "patient": "protected-group",
            }
        ],
    )
    reference = csv(
        tmp_path,
        "training",
        [
            {
                "sample_id": "t1",
                "compound": "protected-compound",
                "patient": "protected-group",
            }
        ],
    )
    audit = prepare_evaluation(
        evaluation,
        definition(entity_columns=["compound"], group_columns=["patient"]),
        training_reference=reference,
        reference_complete=True,
    ).artifact["audit"]
    assert audit["findings"]["sample_id_overlap"]["status"] == "pass"
    assert audit["findings"]["entity_overlap"]["status"] == "fail"
    assert audit["findings"]["group_overlap"]["status"] == "fail"


def test_allowed_repeats_and_numeric_label_tolerance_do_not_create_false_failures(
    tmp_path,
):
    evaluation = csv(
        tmp_path,
        "evaluation",
        [
            {"sample_id": "e1", "entity": "replicate", "target": 1.0},
            {"sample_id": "e2", "entity": "replicate", "target": 1.02},
        ],
    )
    reference = csv(
        tmp_path, "training", [{"sample_id": "t1", "entity": "other", "target": 3.0}]
    )
    rules = definition(
        entity_columns=["entity"],
        label_column="target",
        conflicting_labels="forbid",
        label_tolerance=0.05,
    )
    audit = prepare_evaluation(
        evaluation, rules, training_reference=reference, reference_complete=True
    ).artifact["audit"]
    assert (
        audit["status"] == "pass"
        and audit["findings"]["repeated_entities"]["affected_records"] == 2
    )
    changed = rules.as_dict()
    changed["label_tolerance"] = 0.001
    assert (
        prepare_evaluation(
            evaluation,
            EvaluationDesign.from_dict(changed),
            training_reference=reference,
            reference_complete=True,
        ).artifact["audit"]["findings"]["conflicting_labels"]["status"]
        == "fail"
    )


def test_partition_selection_exclusions_and_training_retention_are_explicit(tmp_path):
    evaluation = csv(
        tmp_path,
        "evaluation",
        [
            {"sample_id": "train-id", "split": "train", "qc": False},
            {"sample_id": "test-ok", "split": "test", "qc": True},
            {"sample_id": "test-excluded", "split": "test", "qc": False},
        ],
    )
    reference = csv(
        tmp_path,
        "training",
        [
            {"sample_id": "train-id", "split": "train"},
            {"sample_id": "test-ok", "split": "test"},
        ],
    )
    rules = definition(
        split_column="split",
        exclusions=[{"column": "qc", "operator": "equals", "value": False}],
    )
    prepared = prepare_evaluation(
        evaluation, rules, training_reference=reference, reference_complete=True
    )
    assert prepared.frame.sample_id.tolist() == ["test-ok"]
    assert prepared.artifact["audit"]["excluded_evaluation_records"] == 1
    assert prepared.artifact["audit"]["n_reference_records"] == 1
    assert prepared.artifact["audit"]["status"] == "pass"
    # An excluded QC status must not erase an actual training record from the audit.
    leaked = pd.read_csv(evaluation)
    leaked.loc[0, "sample_id"] = "test-ok"
    leaked.to_csv(evaluation, index=False)
    failed = prepare_evaluation(
        evaluation, rules, training_reference=reference, reference_complete=True
    )
    assert failed.artifact["audit"]["findings"]["sample_id_overlap"]["status"] == "fail"


def test_chronology_detects_out_of_time_training_and_reports_missing_evidence(tmp_path):
    evaluation = csv(
        tmp_path, "evaluation", [{"sample_id": "e1", "collected": "2025-02-01"}]
    )
    reference = csv(
        tmp_path, "training", [{"sample_id": "t1", "collected": "2025-03-01"}]
    )
    rules = definition(chronology={"column": "collected", "cutoff": "2025-01-01"})
    audit = prepare_evaluation(
        evaluation, rules, training_reference=reference, reference_complete=True
    ).artifact["audit"]
    assert audit["findings"]["chronology"]["status"] == "fail"
    reference = csv(tmp_path, "training", [{"sample_id": "t1"}])
    assert (
        prepare_evaluation(
            evaluation, rules, training_reference=reference, reference_complete=True
        ).artifact["audit"]["findings"]["chronology"]["status"]
        == "not_testable"
    )


def test_optional_molecular_identity_and_scaffolds_have_distinct_scopes(tmp_path):
    pytest.importorskip("rdkit")
    evaluation = csv(tmp_path, "evaluation", [{"sample_id": "e1", "smiles": "CCO"}])
    reference = csv(tmp_path, "training", [{"sample_id": "t1", "smiles": "OCC"}])
    adapter = {"name": "rdkit-molecule/v1", "smiles_column": "smiles"}
    assert (
        prepare_evaluation(
            evaluation,
            definition(adapter=adapter),
            training_reference=reference,
            reference_complete=True,
        ).artifact["audit"]["findings"]["molecular_identity"]["status"]
        == "fail"
    )
    evaluation = csv(
        tmp_path, "evaluation", [{"sample_id": "e1", "smiles": "Cc1ccccc1"}]
    )
    reference = csv(tmp_path, "training", [{"sample_id": "t1", "smiles": "Oc1ccccc1"}])
    result = prepare_evaluation(
        evaluation,
        definition(adapter={**adapter, "scaffold_overlap": "forbid"}),
        training_reference=reference,
        reference_complete=True,
    ).artifact
    assert result["audit"]["findings"]["molecular_identity"]["status"] == "pass"
    assert result["audit"]["findings"]["scaffold_overlap"]["status"] == "fail"
    assert result["audit"]["adapter_version"]
    evaluation = csv(tmp_path, "evaluation", [{"sample_id": "e1", "smiles": "CCO"}])
    reference = csv(tmp_path, "training", [{"sample_id": "t1", "smiles": "CCC"}])
    acyclic = prepare_evaluation(
        evaluation,
        definition(adapter={**adapter, "scaffold_overlap": "forbid"}),
        training_reference=reference,
        reference_complete=True,
    ).artifact["audit"]
    assert acyclic["findings"]["scaffold_overlap"]["status"] == "not_testable"
    assert acyclic["findings"]["scaffold_overlap"]["affected_records"] is None


def test_optional_near_duplicates_are_heuristic_and_budgeted(tmp_path):
    pytest.importorskip("rdkit")
    evaluation = csv(tmp_path, "evaluation", [{"sample_id": "e1", "smiles": "CCCCCCC"}])
    reference = csv(
        tmp_path,
        "training",
        [
            {"sample_id": "t1", "smiles": "CCCCCCCC"},
            {"sample_id": "t2", "smiles": "CCCCCCCCC"},
        ],
    )
    adapter = {
        "name": "rdkit-molecule/v1",
        "smiles_column": "smiles",
        "near_duplicates": {"threshold": 0.5, "max_pairs": 10},
    }
    result = prepare_evaluation(
        evaluation,
        definition(adapter=adapter),
        training_reference=reference,
        reference_complete=True,
    ).artifact["audit"]
    assert result["findings"]["near_duplicates"]["status"] == "warn"
    assert (
        result["findings"]["near_duplicates"]["reason"] == "morgan_tanimoto_heuristic"
    )
    adapter["near_duplicates"]["max_pairs"] = 1
    limited = prepare_evaluation(
        evaluation,
        definition(adapter=adapter),
        training_reference=reference,
        reference_complete=True,
    ).artifact["audit"]
    assert limited["findings"]["near_duplicates"]["status"] == "not_testable"
    assert limited["findings"]["near_duplicates"]["reason"] == "pair_budget_exceeded"


def test_audited_pipeline_scores_exact_eligible_rows_and_keeps_protected_evidence_local(
    tmp_path, monkeypatch, capsys
):
    import yaml

    from privatelabbench.reports.receipt import verify_receipt

    current = run_table(tmp_path, "current")
    training = csv(
        tmp_path,
        "training",
        [{"sample_id": f"train-{i}", "split": "train"} for i in range(10)],
    )
    rules = tmp_path / "design.yaml"
    rules.write_text(yaml.safe_dump(run_rules().as_dict()))
    policy = tmp_path / "release.yaml"
    policy.write_text(yaml.safe_dump(release_policy()))
    output = tmp_path / "results"
    before = Path(current).read_bytes()
    assert (
        invoke(
            monkeypatch,
            [
                "evaluate",
                current,
                "--evaluation-design",
                rules,
                "--training-reference",
                training,
                "--reference-complete",
                "--release-policy",
                policy,
                "--baseline-column",
                "baseline",
                "--output-dir",
                output,
                "--resamples",
                "100",
            ],
        )
        == 0
    )
    assert Path(current).read_bytes() == before
    report = json.loads((output / "evaluation.json").read_text())
    assert report["result"]["n_samples"] == 20
    assert report["result"]["clean_metrics"]["mae"] == pytest.approx(0.1)
    assert report["result"]["baseline_metrics"]["mae"] == pytest.approx(0.3)
    assert report["result"]["design_audit"]["status"] == "pass"
    public = output / "evaluation_receipt.shareable.json"
    assert verify_receipt(public)["valid"]
    text = public.read_text()
    assert (
        "protected-" not in text
        and "excluded-" not in text
        and "training.csv" not in text
    )
    shared = json.loads(text)["shareable"]["evaluation"]["design_audit"]
    assert shared["n_evaluation_records"] == 20 and shared["status"] == "pass"
    local = json.loads((output / "evaluation_receipt.json").read_text())
    assert local["local"]["design_audits"][0]["artifact"]["local"][
        "training_reference_sha256"
    ]
    assert "Design audit         pass" in capsys.readouterr().out


def test_failed_audit_stops_before_scoring_and_local_debugging_cannot_publish(
    tmp_path, monkeypatch
):
    import yaml

    from privatelabbench.quality import evaluate_quality_gate

    current = run_table(tmp_path, "current")
    training = csv(
        tmp_path,
        "training",
        [
            {"sample_id": "current-protected-0", "split": "train"},
            *[{"sample_id": f"train-{i}", "split": "train"} for i in range(9)],
        ],
    )
    rules = tmp_path / "design.yaml"
    rules.write_text(yaml.safe_dump(run_rules().as_dict()))
    policy = tmp_path / "release.yaml"
    policy.write_text(
        yaml.safe_dump({**release_policy(), "require_design_audit": False})
    )
    output = tmp_path / "results"
    output.mkdir()
    public = output / "evaluation_receipt.shareable.json"
    public.write_text("old-public-result")
    args = [
        "evaluate",
        current,
        "--evaluation-design",
        rules,
        "--training-reference",
        training,
        "--reference-complete",
        "--release-policy",
        policy,
        "--output-dir",
        output,
        "--resamples",
        "100",
    ]
    assert invoke(monkeypatch, args) == 1
    assert not public.exists() and not (output / "evaluation.json").exists()
    audit = json.loads((output / "evaluation_design_audit.json").read_text())
    assert audit["audit"]["status"] == "fail"
    quality = {
        "schema_version": "quality-policy/v1",
        "design": {"require_pass": True, "max_overlap_records": 0},
    }
    assert evaluate_quality_gate(audit, quality)["status"] == "fail"
    assert invoke(monkeypatch, [*args, "--design-failure-mode", "local_only"]) == 1
    assert (output / "evaluation_receipt.json").exists() and not public.exists()
    release = json.loads(public.with_suffix(".release-audit.json").read_text())
    assert (
        release["decision"] == "deny"
        and "evaluation_design_failed" in release["reason_codes"]
    )


def test_unknown_training_evidence_cannot_satisfy_quality_or_strict_release(
    tmp_path, monkeypatch
):
    import yaml

    from privatelabbench.quality import evaluate_quality_gate

    current = run_table(tmp_path, "current")
    rules = tmp_path / "design.yaml"
    rules.write_text(yaml.safe_dump(run_rules().as_dict()))
    policy = tmp_path / "release.yaml"
    policy.write_text(yaml.safe_dump(release_policy()))
    output = tmp_path / "results"
    assert (
        invoke(
            monkeypatch,
            [
                "evaluate",
                current,
                "--evaluation-design",
                rules,
                "--release-policy",
                policy,
                "--output-dir",
                output,
                "--resamples",
                "100",
            ],
        )
        == 0
    )
    assert not (output / "evaluation_receipt.shareable.json").exists()
    local = json.loads((output / "evaluation_receipt.json").read_text())
    assert local["shareable"]["evaluation"]["design_audit"]["status"] == "not_testable"
    assert (
        evaluate_quality_gate(
            local,
            {
                "schema_version": "quality-policy/v1",
                "design": {"require_pass": True, "max_overlap_records": 0},
            },
        )["status"]
        == "investigate"
    )


def test_reference_diagnostics_apply_the_same_design_before_both_scores(
    tmp_path, monkeypatch
):
    import yaml

    current = run_table(tmp_path, "current", error=0.4)
    reference = run_table(tmp_path, "reference", error=0.1)
    training = csv(
        tmp_path,
        "training",
        [{"sample_id": f"train-{i}", "split": "train"} for i in range(10)],
    )
    rules = tmp_path / "design.yaml"
    rules.write_text(yaml.safe_dump(run_rules().as_dict()))
    output = tmp_path / "results"
    assert (
        invoke(
            monkeypatch,
            [
                "evaluate",
                current,
                "--reference",
                reference,
                "--evaluation-design",
                rules,
                "--training-reference",
                training,
                "--reference-complete",
                "--output-dir",
                output,
                "--resamples",
                "100",
                "--primary-metric",
                "mae",
            ],
        )
        == 0
    )
    report = json.loads((output / "evaluation.json").read_text())
    summary = report["result"]["degradation_summary"]
    assert summary["n_reference"] == summary["n_current"] == 20
    assert summary["overall"]["mae"]["degradation"] == pytest.approx(0.3)
    assert report["result"]["reference_design_audit"]["status"] == "pass"


def test_standalone_cli_audit_is_local_only_and_can_feed_a_quality_gate(
    tmp_path, monkeypatch, capsys
):
    import yaml

    current = run_table(tmp_path, "current")
    training = csv(
        tmp_path,
        "training",
        [{"sample_id": f"train-{i}", "split": "train"} for i in range(10)],
    )
    rules = tmp_path / "design.yaml"
    rules.write_text(yaml.safe_dump(run_rules().as_dict()))
    audit = tmp_path / "audit.json"
    assert (
        invoke(
            monkeypatch,
            [
                "audit-design",
                "--evaluation",
                current,
                "--training-reference",
                training,
                "--reference-complete",
                "--protocol",
                rules,
                "--out",
                audit,
            ],
        )
        == 0
    )
    assert json.loads(audit.read_text())["scope"] == "local"
    assert "protected-" not in capsys.readouterr().out
    quality = tmp_path / "quality.yaml"
    quality.write_text(
        "schema_version: quality-policy/v1\ndesign:\n  require_pass: true\n  max_overlap_records: 0\n"
    )
    assert invoke(monkeypatch, ["gate", audit, "--policy", quality]) == 0
    before = Path(current).read_bytes()
    assert (
        invoke(
            monkeypatch,
            [
                "audit-design",
                "--evaluation",
                current,
                "--protocol",
                rules,
                "--out",
                current,
            ],
        )
        == 2
    )
    assert Path(current).read_bytes() == before


def test_paired_comparison_applies_the_same_eligibility_and_binds_both_audits(
    tmp_path, monkeypatch
):
    import yaml

    from privatelabbench.reports.integrity import verify_report

    current = run_table(tmp_path, "candidate")
    baseline = tmp_path / "baseline.csv"
    frame = pd.read_csv(current)
    frame["prediction"] = frame["baseline"]
    frame.to_csv(baseline, index=False)
    training = csv(
        tmp_path,
        "training",
        [{"sample_id": f"train-{i}", "split": "train"} for i in range(10)],
    )
    rules = tmp_path / "design.yaml"
    rules.write_text(yaml.safe_dump(run_rules().as_dict()))
    policy = tmp_path / "release.yaml"
    policy.write_text(yaml.safe_dump(release_policy()))
    output, markdown = tmp_path / "pair.json", tmp_path / "pair.md"
    assert (
        invoke(
            monkeypatch,
            [
                "compare",
                current,
                baseline,
                "--target",
                "target",
                "--task-type",
                "regression",
                "--metric",
                "mae",
                "--evaluation-design",
                rules,
                "--training-reference",
                training,
                "--reference-complete",
                "--resamples",
                "100",
                "--permutations",
                "0",
                "--release-policy",
                policy,
                "--json-report",
                output,
                "--report",
                markdown,
            ],
        )
        == 0
    )
    local = json.loads(output.read_text())
    assert local["shareable"]["n_samples"] == 20
    assert local["shareable"]["improvement_a_over_b"] == pytest.approx(0.2)
    assert len(local["local"]["design_audits"]) == 2
    public = tmp_path / "pair.shareable.json"
    assert verify_report(str(public))["valid"]
    shared = json.loads(public.read_text())["shareable"]
    assert {audit["model_role"] for audit in shared["design_audits"]} == {
        "model_a",
        "model_b",
    }
    assert (
        "protected-" not in public.read_text()
        and "training.csv" not in public.read_text()
    )


def test_protocol_design_is_immutable_and_qc_does_not_copy_data_into_config(
    tmp_path, monkeypatch
):
    import yaml

    from privatelabbench.config import load_config
    from privatelabbench.protocols import EvaluationProtocol, resolve_protocol

    rules = resolve_protocol("plb://generic/regression@1.0.0").as_dict()
    original_hash = resolve_protocol("plb://generic/regression@1.0.0").sha256
    rules["version"] = "1.1.0"
    rules["evaluation_design"] = run_rules().as_dict()
    protocol = EvaluationProtocol.from_dict(rules)
    assert protocol.sha256 != original_hash
    file = tmp_path / "protocol.yaml"
    file.write_text(yaml.safe_dump(protocol.as_dict()))
    current = run_table(tmp_path, "candidate")
    config = tmp_path / "evaluation.yaml"
    assert (
        invoke(monkeypatch, ["init", current, "--protocol", file, "--out", config]) == 0
    )
    loaded = load_config(str(config))
    assert loaded.raw["evaluation_design"]["exclusions"][0]["value"] is False
    assert "candidate-protected-0" not in config.read_text()
    assert "candidate-protected-0" not in repr(loaded)


def test_public_audit_summary_suppresses_small_cells_and_failed_evidence_cannot_be_waived(
    tmp_path,
):
    from copy import deepcopy

    from privatelabbench.design_audit import sanitize_design_audit
    from privatelabbench.privacy.export import check_release

    current = run_table(tmp_path, "candidate")
    training = csv(
        tmp_path,
        "training",
        [{"sample_id": f"train-{i}", "split": "train"} for i in range(10)],
    )
    audit = prepare_evaluation(
        current, run_rules(), training_reference=training, reference_complete=True
    ).artifact["audit"]
    assert sanitize_design_audit(audit, release_policy())["status"] == "pass"
    smaller = deepcopy(audit)
    smaller["excluded_evaluation_records"] = 1
    smaller["n_input_records"] -= 4
    assert (
        sanitize_design_audit(smaller, release_policy())["status"]
        == "withheld_small_audit_cells"
    )
    failed = deepcopy(audit)
    finding = failed["findings"]["sample_id_overlap"]
    finding["status"], finding["affected_records"] = "fail", 2
    failed["status"] = "fail"
    artifact = {
        "schema_version": "evaluation-receipt/v1",
        "shareable": {"evaluation": {"design_audit": failed}, "privacy": {}},
    }
    decision, public = check_release(
        artifact,
        {**release_policy(), "require_design_audit": False},
        evidence={"design_audits": [], "gates": []},
    )
    assert decision.decision == "deny" and public is None


def test_artifact_summary_protocol_and_quality_schemas_match_runtime(tmp_path):
    import yaml
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    from privatelabbench.design_audit import sanitize_design_audit
    from privatelabbench.protocols import EvaluationProtocol, resolve_protocol

    current = run_table(tmp_path, "current")
    training = csv(
        tmp_path,
        "training",
        [{"sample_id": f"train-{i}", "split": "train"} for i in range(10)],
    )
    audit = prepare_evaluation(
        current, run_rules(), training_reference=training, reference_complete=True
    ).artifact
    root = Path("privatelabbench/data/schemas")
    names = [
        "evaluation-design-v1.schema.json",
        "evaluation-design-audit-summary-v1.schema.json",
        "evaluation-design-audit-v1.schema.json",
        "quality-policy-v1.schema.json",
        "release-policy-v1.schema.json",
        "sampling-design-v1.schema.json",
        "multiplicity-policy-v1.schema.json",
    ]
    schemas = {name: json.loads((root / name).read_text()) for name in names}
    registry = Registry().with_resources(
        (name, Resource.from_contents(schema)) for name, schema in schemas.items()
    )
    Draft202012Validator(
        schemas["evaluation-design-audit-v1.schema.json"], registry=registry
    ).validate(audit)
    Draft202012Validator(
        schemas["evaluation-design-audit-summary-v1.schema.json"]
    ).validate(sanitize_design_audit(audit["audit"], release_policy()))
    Draft202012Validator(schemas["quality-policy-v1.schema.json"]).validate(
        {
            "schema_version": "quality-policy/v1",
            "design": {"require_pass": True, "max_overlap_records": 0},
        }
    )
    rule = resolve_protocol("plb://generic/regression@1.0.0").as_dict()
    rule["version"] = "1.1.0"
    rule["evaluation_design"] = run_rules().as_dict()
    protocol = EvaluationProtocol.from_dict(rule)
    Draft202012Validator(
        json.loads((root / "evaluation-protocol-v1.schema.json").read_text()),
        registry=registry,
    ).validate(protocol.as_dict())
    example = yaml.safe_load(Path("examples/evaluation_design.yaml").read_text())
    Draft202012Validator(schemas["evaluation-design-v1.schema.json"]).validate(example)
    EvaluationDesign.from_dict(example)


def test_missing_molecular_reference_is_untestable_and_invalid_strings_fail(tmp_path):
    pytest.importorskip("rdkit")
    evaluation = csv(tmp_path, "evaluation", [{"sample_id": "e1", "smiles": "CCO"}])
    reference = csv(tmp_path, "training", [{"sample_id": "t1"}])
    rules = definition(adapter={"name": "rdkit-molecule/v1", "smiles_column": "smiles"})
    unknown = prepare_evaluation(
        evaluation, rules, training_reference=reference, reference_complete=True
    ).artifact["audit"]
    assert unknown["status"] == "not_testable"
    assert unknown["findings"]["invalid_molecules"]["status"] == "not_testable"
    reference = csv(
        tmp_path, "training", [{"sample_id": "t1", "smiles": "not-valid-smiles"}]
    )
    invalid = prepare_evaluation(
        evaluation, rules, training_reference=reference, reference_complete=True
    ).artifact["audit"]
    assert (
        invalid["status"] == "fail"
        and invalid["findings"]["invalid_molecules"]["affected_records"] == 1
    )


def test_mirrored_training_records_do_not_create_false_repeated_entity_failures(
    tmp_path,
):
    evaluation = csv(
        tmp_path,
        "evaluation",
        [
            {"sample_id": "t1", "entity": "train-entity", "split": "train"},
            {"sample_id": "e1", "entity": "evaluation-entity", "split": "test"},
        ],
    )
    reference = csv(
        tmp_path,
        "training",
        [{"sample_id": "t1", "entity": "train-entity", "split": "train"}],
    )
    rules = definition(
        split_column="split", entity_columns=["entity"], repeated_entities="forbid"
    )
    audit = prepare_evaluation(
        evaluation, rules, training_reference=reference, reference_complete=True
    ).artifact["audit"]
    assert (
        audit["status"] == "pass"
        and audit["findings"]["repeated_entities"]["affected_records"] == 0
    )


def test_incomplete_audit_objects_cannot_satisfy_quality_rules():
    from privatelabbench.quality import evaluate_quality_gate

    forged = {
        "schema_version": "evaluation-design-audit/v1",
        "audit": {"status": "pass"},
    }
    decision = evaluate_quality_gate(
        forged,
        {"schema_version": "quality-policy/v1", "design": {"require_pass": True}},
    )
    assert decision["status"] == "investigate"
