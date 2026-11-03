"""Synthetic assay contracts; actual public-data evidence is generated separately."""

import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from privatelabbench.cli import main
from privatelabbench.core.public_data import download_verified
from privatelabbench.integrations import proteingym as pg
from privatelabbench.privacy.export import check_release
from privatelabbench.reports.integrity import verify_payload
from privatelabbench.reports.receipt import verify_receipt

MODEL = {"id": "synthetic-model", "revision": "v1"}


@pytest.fixture
def assays(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    definitions = [
        ("synthetic-a1", "protein-a", "Activity", "Eukaryote", 30, 1),
        ("synthetic-a2", "protein-a", "Activity", "Eukaryote", 30, -1),
        ("synthetic-b", "protein-b", "Activity", "Virus", 35, 1),
        ("synthetic-c", "protein-c", "Binding", "Human", 40, -1),
    ]
    entries = {}
    metadata = []
    tables = []
    for name, protein, function, taxon, n, direction in definitions:
        mutants = [f"A{index + 1}V" for index in range(n)]
        targets = np.arange(n, dtype=float) + 0.125
        frame = pd.DataFrame(
            {
                "mutant": mutants,
                "DMS_score": targets,
                "mutated_sequence": "PRIVATE_SEQUENCE_SENTINEL",
                "DMS_score_bin": np.arange(n) % 2,
            }
        )
        path = root / (name + ".csv")
        frame.to_csv(path, index=False)
        entries[name] = pg.DMSAssay(
            name,
            path.name,
            sha256(path.read_bytes()).hexdigest(),
            protein,
            function,
            taxon,
            n,
        )
        metadata.append(
            {
                "DMS_id": name,
                "UniProt_ID": protein,
                "coarse_selection_type": function,
                "taxon": taxon,
                "DMS_filename": path.name,
                "DMS_total_number_mutants": n,
            }
        )
        tables.append(
            pd.DataFrame(
                {
                    "assay": name,
                    "mutant": mutants,
                    "prediction": direction * targets,
                    "private_feature": "PRIVATE_FEATURE_SENTINEL",
                }
            )
        )
    reference = root / pg.REFERENCE_FILE
    pd.DataFrame(metadata).to_csv(reference, index=False)
    monkeypatch.setattr(pg, "ASSAYS", entries)
    monkeypatch.setattr(
        pg, "REFERENCE_SHA256", sha256(reference.read_bytes()).hexdigest()
    )
    monkeypatch.setattr(pg, "BENCHMARK_VERSION", "synthetic-contract-fixture")
    monkeypatch.setattr(pg, "REGISTRY", {**pg.REGISTRY, "full_assay_count": 4})
    prediction = tmp_path / "scores.csv"
    pd.concat(tables, ignore_index=True).sample(frac=1, random_state=13).to_csv(
        prediction, index=False
    )
    return root, list(entries), prediction, tmp_path


def evaluate(assays, **kwargs):
    root, names, path, tmp_path = assays
    return pg.evaluate_proteingym(
        root,
        names,
        path,
        tmp_path / "evaluation",
        model=MODEL,
        score_direction=kwargs.pop("score_direction", "higher"),
        **kwargs,
    )


def policy(assays):
    _, names, _, _ = assays
    return {
        "schema_version": "release-policy/v1",
        "id": "reviewed-synthetic",
        "enabled": True,
        "require_privacy_audit": False,
        "include_protocol": True,
        "public_models": [MODEL],
        "public_assays": names,
        "public_benchmark": pg.benchmark_identity(),
    }


def test_variant_templates_and_assay_receipts_preserve_all_records(assays):
    root, names, _, tmp_path = assays
    output = tmp_path / "template.csv"
    pg.prepare_template(root, names, output)
    frame = pd.read_csv(output)
    assert (
        list(frame) == ["assay", "sample_id", "prediction"]
        and frame.sample_id.is_unique
    )
    assert (
        len(frame) == 135
        and "DMS_score" not in output.read_text()
        and "PRIVATE_SEQUENCE" not in output.read_text()
    )
    result = evaluate(assays)
    assert verify_payload(result["artifact"])["valid"]
    for name in names:
        path = tmp_path / "evaluation" / name / "evaluation_receipt.json"
        assert verify_receipt(path)["valid"]
        receipt = json.loads(path.read_text())
        assert set(receipt["shareable"]["evaluation"]["metrics"]) == {"spearman"}
        assert receipt["shareable"]["benchmark"]["id"] == name
    assert not (tmp_path / "evaluation/proteingym_result.shareable.json").exists()


def test_hierarchical_grouping_avoids_naive_assay_or_variant_pooling(assays):
    shared = evaluate(assays)["artifact"]["shareable"]
    assert shared["metrics"]["spearman"] == pytest.approx(-0.25)
    assert np.mean([row["spearman"] for row in shared["per_assay"]]) == pytest.approx(
        0.0
    )
    assert len(shared["per_protein_function"]) == 3 and len(shared["per_function"]) == 2
    assert shared["benchmark_scope"] == "selected_assay_subset"
    assert shared["uncertainty_scope"] == "point_estimates_no_aggregate_bootstrap"


def test_upstream_rounds_each_assay_before_group_averaging():
    rows = [
        {
            "assay": "a",
            "uniprot_id": "p",
            "function": "Activity",
            "taxon": "Human",
            "n_variants": 30,
            "spearman": 0.1235,
        },
        {
            "assay": "b",
            "uniprot_id": "q",
            "function": "Activity",
            "taxon": "Human",
            "n_variants": 30,
            "spearman": 0.1244,
        },
    ]
    summary = pg.summarize_assays(rows)
    assert summary["metrics"]["spearman"] == pytest.approx(0.124)
    assert summary["per_assay"][0]["spearman"] == 0.1235
    assert summary["per_assay"][0]["aggregation_spearman"] == 0.124


def test_lower_score_orientation_is_explicit_and_reverses_assay_correlations(assays):
    shared = evaluate(assays, score_direction="lower")["artifact"]["shareable"]
    assert shared["metrics"]["spearman"] == pytest.approx(0.25)


def test_constant_model_scores_remain_undefined_and_are_not_silently_dropped(assays):
    _, _, path, _ = assays
    frame = pd.read_csv(path)
    frame.loc[frame.assay == "synthetic-a1", "prediction"] = 1
    frame.to_csv(path, index=False)
    shared = evaluate(assays)["artifact"]["shareable"]
    assert (
        shared["metrics"]["spearman"] is None
        and shared["status"] == "undefined_assay_score"
    )
    assert len(shared["per_assay"]) == 4


@pytest.mark.parametrize(
    "damage", ["missing", "duplicate", "wrong_assay", "targets", "nonfinite"]
)
def test_invalid_score_coverage_and_targets_are_rejected(assays, damage):
    _, _, path, tmp_path = assays
    frame = pd.read_csv(path)
    if damage == "missing":
        frame = frame.iloc[:-1]
    elif damage == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]], ignore_index=True)
    elif damage == "wrong_assay":
        frame.loc[0, "assay"] = "unknown"
    elif damage == "targets":
        frame["DMS_score"] = 9999
    else:
        frame.loc[0, "prediction"] = np.nan
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError):
        evaluate(assays)
    assert not (tmp_path / "evaluation/proteingym_result.shareable.json").exists()


def test_single_assay_native_mutant_score_files_need_no_manual_namespace(assays):
    root, names, path, tmp_path = assays
    frame = pd.read_csv(path)
    frame = frame[frame.assay == names[0]].drop(columns=["assay"])
    frame.to_csv(path, index=False)
    result = pg.evaluate_proteingym(
        root, [names[0]], path, tmp_path / "one", model=MODEL, score_direction="higher"
    )
    assert result["artifact"]["shareable"]["metrics"]["spearman"] == pytest.approx(1.0)


def test_model_coverage_release_and_private_metadata_are_reviewed(assays):
    artifact = evaluate(assays)["artifact"]
    artifact["shareable"]["metrics"]["spearman"] = 1
    artifact["shareable"]["per_assay"][0]["raw_sequence"] = "PRIVATE_SEQUENCE_SENTINEL"
    decision, public = check_release(artifact, policy(assays))
    assert decision.decision == "allow"
    assert public["shareable"]["metrics"]["spearman"] == pytest.approx(-0.25)
    text = json.dumps(public)
    assert (
        "PRIVATE_SEQUENCE" not in text
        and "PRIVATE_FEATURE" not in text
        and ":A1V" not in text
        and "prediction_sha256" not in text
    )
    blocked = policy(assays)
    blocked["public_assays"] = blocked["public_assays"][:-1]
    assert check_release(artifact, blocked)[1] is None
    blocked = policy(assays)
    blocked["min_samples"] = 31
    assert check_release(artifact, blocked)[1] is None


def test_cache_drift_and_failed_cli_rerun_remove_stale_public(assays, monkeypatch):
    root, names, path, tmp_path = assays
    release = tmp_path / "release.yaml"
    release.write_text(yaml.safe_dump(policy(assays)))
    output = tmp_path / "cli"
    args = [
        "plb",
        "proteingym-evaluate",
        str(path),
        "--cache-dir",
        str(root),
        "--model",
        "synthetic-model@v1",
        "--score-direction",
        "higher",
        "--release-policy",
        str(release),
        "--output-dir",
        str(output),
    ]
    for name in names:
        args.extend(["--assay", name])
    monkeypatch.setattr("sys.argv", args)
    assert main() == 0
    public = output / "proteingym_result.shareable.json"
    assert verify_payload(json.loads(public.read_text()))["valid"]
    (root / (names[0] + ".csv")).write_text("changed assay")
    assert main() == 2
    assert not public.exists() and not (output / "proteingym_result.md").exists()


def test_optional_blosum_baseline_has_frozen_reference_values():
    pytest.importorskip("Bio")
    from scripts.validate_proteingym import blosum_scores

    np.testing.assert_array_equal(
        blosum_scores(["A1V", "M2I", "A1V:M2I"]), [-4, -4, -8]
    )


def test_verified_download_preserves_conflicting_files_and_never_commits_bad_bytes(
    tmp_path, monkeypatch
):
    import privatelabbench.core.public_data as module

    data = b"public reference bytes"
    digest = sha256(data).hexdigest()
    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: BytesIO(data))
    path = tmp_path / "asset"
    download_verified(path, "https://example.invalid/data", digest)
    assert path.read_bytes() == data
    path.write_bytes(b"private file")
    with pytest.raises(ValueError):
        download_verified(path, "https://example.invalid/data", digest)
    assert path.read_bytes() == b"private file"
    invalid = tmp_path / "invalid"
    with pytest.raises(ValueError):
        download_verified(invalid, "https://example.invalid/data", "a" * 64)
    assert not invalid.exists() and not list(tmp_path.glob(".plb-reference-*"))


def test_result_schema_and_private_single_assay_protocol(assays, monkeypatch):
    from jsonschema import Draft202012Validator

    from privatelabbench.reports.integrity import attach_integrity_metadata

    result = evaluate(assays)
    directory = Path(pg.__file__).parents[1] / "data/schemas"
    validator = Draft202012Validator(
        json.loads((directory / "proteingym-evaluation-v1.schema.json").read_text())
    )
    validator.validate(result["artifact"])
    decision, public = check_release(result["artifact"], policy(assays))
    assert decision.decision == "allow"
    validator.validate(attach_integrity_metadata(public))
    root, names, _, tmp_path = assays
    frame = pg.load_assay(root, names[0]).frame[["sample_id", "target", "assay"]].copy()
    frame["prediction"] = frame.target * 2 + 10
    table = tmp_path / "private.csv"
    frame.to_csv(table, index=False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "plb",
            "evaluate",
            str(table),
            "--protocol",
            pg.PROTOCOL,
            "--output-dir",
            str(tmp_path / "private-result"),
        ],
    )
    assert main() == 0
    receipt = json.loads(
        (tmp_path / "private-result/evaluation_receipt.json").read_text()
    )
    assert set(receipt["shareable"]["evaluation"]["metrics"]) == {"spearman"}
    assert not (tmp_path / "private-result/evaluation_receipt.shareable.json").exists()


def test_private_protocol_refuses_a_pooled_multi_assay_table(assays, monkeypatch):
    root, names, _, tmp_path = assays
    frames = []
    for name in names:
        frame = pg.load_assay(root, name).frame[["sample_id", "target", "assay"]].copy()
        frame["prediction"] = frame.target
        frames.append(frame)
    path = tmp_path / "mixed.csv"
    pd.concat(frames, ignore_index=True).to_csv(path, index=False)
    monkeypatch.setattr(
        "sys.argv",
        [
            "plb",
            "evaluate",
            str(path),
            "--protocol",
            pg.PROTOCOL,
            "--output-dir",
            str(tmp_path / "mixed-result"),
        ],
    )
    assert main() == 2
    assert not (tmp_path / "mixed-result/evaluation_receipt.shareable.json").exists()
