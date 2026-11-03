import json
import shutil
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from privatelabbench.cli import main
from privatelabbench.reports.receipt import verify_receipt
from privatelabbench.scoring import LinearJSONAdapter, score_local, validate_manifest

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/trusted_scoring"
UNITS = {"molecular_weight": "g/mol", "logp": "dimensionless"}


@pytest.fixture
def fixture(tmp_path):
    folder = tmp_path / "model"
    shutil.copytree(EXAMPLE, folder)
    return folder, tmp_path


def score(fixture, **options):
    folder, tmp_path = fixture
    return score_local(
        folder / "manifest.yaml",
        folder / "inputs.csv",
        options.pop("output", tmp_path / "predictions.csv"),
        data_units=options.pop("data_units", UNITS),
        dataset_version=options.pop("dataset_version", "synthetic-v1"),
        **options,
    )


def change_manifest(folder, edit):
    path = folder / "manifest.yaml"
    manifest = yaml.safe_load(path.read_text())
    edit(manifest)
    path.write_text(yaml.safe_dump(manifest))


def change_artifact(folder, edit):
    path = folder / "model.json"
    model = json.loads(path.read_text())
    edit(model)
    path.write_text(json.dumps(model))
    digest = sha256(path.read_bytes()).hexdigest()

    def update(manifest):
        manifest["artifact"]["sha256"] = digest
        manifest["model"]["artifact_sha256"] = digest

    change_manifest(folder, update)


def test_frozen_reference_predictions_units_order_ids_and_determinism(fixture):
    folder, tmp_path = fixture
    first = score(fixture)
    table = pd.read_csv(first["predictions"])
    raw = pd.read_csv(folder / "inputs.csv")
    expected = -0.01 * raw.molecular_weight - 0.5 * raw.logp + 1
    np.testing.assert_allclose(table.prediction, expected, rtol=0, atol=1e-14)
    assert list(table) == ["sample_id", "prediction"]
    assert list(table.sample_id) == list(raw.sample_id)
    second = score(fixture, output=tmp_path / "second.csv")
    assert first["prediction_sha256"] == second["prediction_sha256"]
    info = json.loads(Path(first["provenance"]).read_text())
    assert info["scope"] == "local" and info["isolation"] == "none_trusted_in_process"
    assert "mol-001" not in json.dumps(info) and "-0.9" not in json.dumps(info)
    assert not list(tmp_path.glob("*.shareable.json"))


@pytest.mark.parametrize(
    "damage",
    [
        "untrusted",
        "adapter",
        "network",
        "pickle",
        "remote",
        "digest",
        "feature_order",
        "postprocess",
    ],
)
def test_unsupported_or_unapproved_models_rejected(fixture, damage):
    folder, tmp_path = fixture

    def edit(manifest):
        if damage == "untrusted":
            manifest["trust"] = "untrusted_isolated"
        elif damage == "adapter":
            manifest["adapter"]["id"] = "downloaded.custom_module"
        elif damage == "network":
            manifest["permissions"]["network"] = True
        elif damage == "pickle":
            manifest["artifact"]["format"] = "pickle"
        elif damage == "remote":
            manifest["artifact"]["path"] = "https://example.org/weights.json"
        elif damage == "digest":
            manifest["artifact"]["sha256"] = manifest["model"]["artifact_sha256"] = (
                "a" * 64
            )
        elif damage == "feature_order":
            manifest["features"].reverse()
        else:
            manifest["postprocessing"]["version"] = "arbitrary-code/v1"

    change_manifest(folder, edit)
    with pytest.raises(ValueError):
        score(fixture)
    assert not (tmp_path / "predictions.csv").exists()


@pytest.mark.parametrize(
    "damage",
    ["missing_feature", "missing_value", "duplicate_id", "missing_id", "nonfinite"],
)
def test_invalid_private_inputs_rejected_before_output(fixture, damage):
    folder, tmp_path = fixture
    path = folder / "inputs.csv"
    frame = pd.read_csv(path)
    if damage == "missing_feature":
        frame = frame.drop(columns=["logp"])
    elif damage == "missing_value":
        frame.loc[0, "logp"] = np.nan
    elif damage == "duplicate_id":
        frame.loc[1, "sample_id"] = frame.loc[0, "sample_id"]
    elif damage == "missing_id":
        frame.loc[0, "sample_id"] = None
    else:
        frame.loc[0, "logp"] = np.inf
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError):
        score(fixture)
    assert not (tmp_path / "predictions.csv").exists()


def test_units_version_and_existing_inputs_preserved(fixture):
    folder, _ = fixture
    with pytest.raises(ValueError, match="units"):
        score(fixture, data_units={**UNITS, "molecular_weight": "kg/mol"})
    with pytest.raises(ValueError, match="version"):
        score(fixture, dataset_version="different")
    before = (folder / "inputs.csv").read_bytes()
    with pytest.raises(ValueError, match="separate"):
        score(fixture, output=folder / "inputs.csv")
    assert (folder / "inputs.csv").read_bytes() == before


def test_frozen_standardization_and_stable_sigmoid(fixture):
    folder, _ = fixture

    def edit(manifest):
        manifest["task_type"] = "classification"
        manifest["postprocessing"] = {
            "version": "sigmoid/v1",
            "class_labels": ["0", "1"],
        }
        manifest["preprocessing"]["version"] = "standardize/v1"

    change_manifest(folder, edit)
    change_artifact(
        folder,
        lambda model: model.update(
            {"mean": [200, 2], "scale": [100, 1], "coefficients": [2000, 0]}
        ),
    )
    summary = score(fixture)
    frame = pd.read_csv(summary["predictions"])
    assert frame.prediction.between(0, 1).all() and np.isfinite(frame.prediction).all()
    raw = pd.read_csv(folder / "inputs.csv")
    logits = ((raw.molecular_weight - 200) / 100) * 2000 + 1
    assert (logits > 500).any() and (logits < -500).any()
    assert np.all(frame.loc[logits > 500, "prediction"] == 1)
    from scipy.special import expit

    np.testing.assert_allclose(frame.prediction, expit(logits), rtol=1e-14, atol=0)


@pytest.mark.parametrize("bad", [[0.1], [np.nan] * 24, [np.inf] * 24, np.ones((24, 2))])
def test_incomplete_or_invalid_adapter_outputs_rejected(fixture, monkeypatch, bad):
    monkeypatch.setattr(LinearJSONAdapter, "predict", lambda *args: bad)
    with pytest.raises(ValueError):
        score(fixture)


def invoke(monkeypatch, folder, output, extra=()):
    monkeypatch.setattr(
        "sys.argv",
        [
            "plb",
            "score",
            "--model",
            str(folder / "manifest.yaml"),
            "--data",
            str(folder / "inputs.csv"),
            "--units",
            str(folder / "units.yaml"),
            "--data-version",
            "synthetic-v1",
            "--output",
            str(output),
            *map(str, extra),
        ],
    )
    return main()


def test_scientific_score_evaluate_receipt_pipeline_is_local_by_default(
    fixture, monkeypatch
):
    folder, tmp_path = fixture
    report = tmp_path / "evaluation"
    assert (
        invoke(
            monkeypatch,
            folder,
            tmp_path / "predictions.csv",
            [
                "--target",
                "target",
                "--protocol",
                "plb://generic/regression@1.0.0",
                "--evaluate-output-dir",
                report,
            ],
        )
        == 0
    )
    receipt = report / "evaluation_receipt.json"
    assert verify_receipt(receipt)["valid"]
    assert not (report / "evaluation_receipt.shareable.json").exists()
    value = json.loads(receipt.read_text())
    assert (
        value["shareable"]["evaluation"]["external_validation"]["model"][
            "artifact_sha256"
        ]
        == sha256((folder / "model.json").read_bytes()).hexdigest()
    )
    assert (
        value["local"]["config_snapshot"]["scoring_provenance"]["isolation"]
        == "none_trusted_in_process"
    )


def test_failed_pipeline_removes_stale_public_outputs_and_preserves_sources(
    fixture, monkeypatch
):
    folder, tmp_path = fixture
    report = tmp_path / "evaluation"
    report.mkdir()
    public = report / "evaluation_receipt.shareable.json"
    markdown = report / "evaluation_receipt.md"
    public.write_text("stale")
    markdown.write_text("stale")
    (folder / "manifest.yaml").write_text("[ invalid yaml")
    assert (
        invoke(
            monkeypatch,
            folder,
            tmp_path / "new.csv",
            [
                "--target",
                "target",
                "--protocol",
                "plb://generic/regression@1.0.0",
                "--evaluate-output-dir",
                report,
            ],
        )
        == 2
    )
    assert not public.exists() and not markdown.exists()
    assert not (tmp_path / "new.csv").exists()


def test_pipeline_protocol_conflict_cannot_publish(fixture, monkeypatch):
    folder, tmp_path = fixture
    report = tmp_path / "evaluation"
    assert (
        invoke(
            monkeypatch,
            folder,
            tmp_path / "predictions.csv",
            [
                "--target",
                "target",
                "--protocol",
                "plb://generic/binary@1.0.1",
                "--evaluate-output-dir",
                report,
            ],
        )
        == 2
    )
    assert not (report / "evaluation_receipt.shareable.json").exists()


def test_invalid_probabilities_rejected(fixture, monkeypatch):
    folder, _ = fixture

    def edit(manifest):
        manifest["task_type"] = "classification"
        manifest["postprocessing"] = {
            "version": "sigmoid/v1",
            "class_labels": ["0", "1"],
        }

    change_manifest(folder, edit)
    monkeypatch.setattr(LinearJSONAdapter, "predict", lambda *args: np.repeat(1.1, 24))
    with pytest.raises(ValueError, match="probabilities"):
        score(fixture)


def test_reviewed_scoring_export_contains_no_features_ids_paths_or_inference_logs(
    fixture, monkeypatch
):
    folder, tmp_path = fixture
    model = yaml.safe_load((folder / "manifest.yaml").read_text())["model"]
    policy = {
        "schema_version": "release-policy/v1",
        "id": "synthetic-reviewed",
        "enabled": True,
        "require_privacy_audit": False,
        "include_protocol": True,
        "public_validation": {
            "model": model,
            "dataset": {"visibility": "undisclosed", "training_overlap": "unknown"},
            "evaluator_relationship": "undisclosed",
        },
    }
    path = tmp_path / "release.yaml"
    path.write_text(yaml.safe_dump(policy))
    report = tmp_path / "evaluation"
    assert (
        invoke(
            monkeypatch,
            folder,
            tmp_path / "predictions.csv",
            [
                "--target",
                "target",
                "--protocol",
                "plb://generic/regression@1.0.0",
                "--evaluate-output-dir",
                report,
                "--release-policy",
                path,
            ],
        )
        == 0
    )
    receipt = report / "evaluation_receipt.shareable.json"
    assert verify_receipt(receipt)["valid"]
    public = receipt.read_text()
    assert (
        "molecular_weight" not in public
        and "mol-001" not in public
        and "Synthetic illustrative" not in public
    )
    assert (
        str(folder) not in public
        and "scoring_provenance" not in public
        and "input_sha256" not in public
    )


def test_changed_predictions_cannot_claim_scoring_provenance(fixture):
    from privatelabbench.scoring import evaluate_scored

    _, tmp_path = fixture
    summary = score(fixture, target_column="target")
    path = Path(summary["predictions"])
    frame = pd.read_csv(path)
    frame.loc[0, "prediction"] += 1
    frame.to_csv(path, index=False)
    report = tmp_path / "evaluation"
    with pytest.raises(ValueError, match="snapshot"):
        evaluate_scored(summary, report, "plb://generic/regression@1.0.0")
    assert not (report / "evaluation_receipt.shareable.json").exists()


def test_reference_manifest_schema(fixture):
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    import privatelabbench.scoring as scoring

    folder, _ = fixture
    directory = Path(scoring.__file__).parent / "data/schemas"
    resources = []
    for path in directory.glob("*.schema.json"):
        value = json.loads(path.read_text())
        resource = Resource.from_contents(value)
        resources.append((path.name, resource))
        if "$id" in value:
            resources.append((value["$id"], resource))
    schema = json.loads((directory / "model-manifest-v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    manifest = yaml.safe_load((folder / "manifest.yaml").read_text())
    Draft202012Validator(
        schema, registry=Registry().with_resources(resources)
    ).validate(manifest)
    assert (
        validate_manifest(manifest)["model"]["artifact_sha256"]
        == sha256((folder / "model.json").read_bytes()).hexdigest()
    )
