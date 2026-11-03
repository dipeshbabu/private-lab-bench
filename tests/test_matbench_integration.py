"""Explicitly synthetic cache contracts; real upstream parity has an opt-in script."""

from dataclasses import replace
from hashlib import sha256
import gzip, json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest
import yaml

from privatelabbench.integrations import matbench
from privatelabbench.privacy.export import check_release
from privatelabbench.protocols import resolve_protocol
from privatelabbench.reports.integrity import verify_payload
from privatelabbench.reports.receipt import verify_receipt


@pytest.fixture(params=list(matbench.TASKS))
def snapshot(tmp_path, monkeypatch, request):
    task = matbench.TASKS[request.param]
    root = tmp_path / "cache"
    root.mkdir()
    n = 101
    targets = [
        bool(index % 2) if task.task_type == "classification" else index + 0.125
        for index in range(n)
    ]
    rows = [
        [
            (
                "Fe-fake"
                if task.input_type == "composition"
                else {
                    "@module": "never_import_this_module",
                    "@class": "NeverInstantiate",
                }
            ),
            target,
        ]
        for target in targets
    ]
    data = {
        "index": list(range(n)),
        "columns": [task.input_type, task.target],
        "data": rows,
    }
    body = gzip.compress(json.dumps(data).encode(), mtime=0)
    (root / task.filename).write_bytes(body)
    prefix = task.name.replace("matbench", "mb").replace("_", "-")
    ids = [f"{prefix}-{index+1:03d}" for index in range(n)]
    folds = {}
    for fold in range(5):
        folds[f"fold_{fold}"] = {
            "train": [value for index, value in enumerate(ids) if index % 5 != fold],
            "test": [value for index, value in enumerate(ids) if index % 5 == fold],
        }
    document = {
        "metadata": {"n_splits": 5, "random_state": 18012019, "shuffle": True},
        "splits": {task.name: folds},
    }
    content = json.dumps(document).encode()
    (root / matbench.FOLDS_FILE).write_bytes(content)
    task = replace(
        task,
        n_samples=n,
        data_sha256=sha256(body).hexdigest(),
        test_sizes=(21, 20, 20, 20, 20),
    )
    monkeypatch.setitem(matbench.TASKS, task.name, task)
    monkeypatch.setattr(matbench, "FOLDS_SHA256", sha256(content).hexdigest())
    monkeypatch.setattr(matbench, "BENCHMARK_VERSION", "synthetic-contract-fixture")
    snapshot = matbench.load_snapshot(root, task.name)
    records = []
    for fold in snapshot.folds:
        for sample in fold["test"]:
            target = snapshot.labels.loc[sample, "target"]
            prediction = (
                (0.2 if target else 0.1)
                if task.task_type == "classification"
                else target + 0.1 * (fold["fold"] + 1)
            )
            if task.task_type == "classification" and fold["fold"] == 4:
                prediction = 0.3 - prediction
            records.append(
                {"fold": fold["fold"], "sample_id": sample, "prediction": prediction}
            )
    path = tmp_path / "external.csv"
    pd.DataFrame(records).sample(frac=1, random_state=13).to_csv(path, index=False)
    return root, task, path, tmp_path


def evaluate(snapshot, **options):
    root, task, path, tmp_path = snapshot
    return matbench.evaluate_matbench(
        root, task.name, path, tmp_path / "evaluation", **options
    )


def test_official_record_keys_folds_and_templates_preserve_all_records(snapshot):
    root, task, _, tmp_path = snapshot
    output = tmp_path / "template.csv"
    result = matbench.prepare_template(root, task.name, output)
    frame = pd.read_csv(output)
    assert result["folds"] == 5 and len(frame) == task.n_samples
    assert (
        list(frame) == ["fold", "sample_id", "prediction"] and frame.sample_id.is_unique
    )
    assert (
        "target" not in output.read_text()
        and "NeverInstantiate" not in output.read_text()
    )
    with pytest.raises(ValueError, match="fresh"):
        matbench.prepare_template(root, task.name, output)


def test_fold_receipts_and_unweighted_official_aggregation(snapshot):
    result = evaluate(snapshot)
    root, task, _, tmp_path = snapshot
    artifact = result["artifact"]
    shared = artifact["shareable"]
    assert verify_payload(artifact)["valid"]
    assert len(shared["folds"]) == 5
    expected = 0.8 if task.task_type == "classification" else 0.3
    assert shared["metrics"][task.metric] == pytest.approx(expected)
    scores = [row["score"] for row in shared["folds"]]
    assert shared["fold_score_statistics"]["std"] == pytest.approx(np.std(scores))
    assert shared["metrics"][task.metric] != pytest.approx(
        np.average(scores, weights=task.test_sizes), abs=1e-6
    )
    for fold in range(5):
        receipt = tmp_path / "evaluation" / f"fold-{fold}" / "evaluation_receipt.json"
        assert verify_receipt(receipt)["valid"]
        payload = json.loads(receipt.read_text())
        assert payload["shareable"]["benchmark"]["id"] == f"{task.name}-fold-{fold}"
        assert (
            payload["shareable"]["evaluation"]["protocol"]
            == resolve_protocol(task.protocol).identity()
        )
    assert not (tmp_path / "evaluation/matbench_result.shareable.json").exists()


@pytest.mark.parametrize(
    "damage", ["missing_fold", "wrong_fold", "duplicate_id", "target", "nonfinite"]
)
def test_invalid_predictions_and_fold_leakage_are_rejected(snapshot, damage):
    root, task, path, tmp_path = snapshot
    frame = pd.read_csv(path)
    if damage == "missing_fold":
        frame = frame[frame.fold != 4]
    elif damage == "wrong_fold":
        frame.loc[0, "fold"] = (frame.loc[0, "fold"] + 1) % 5
    elif damage == "duplicate_id":
        frame.loc[1, "sample_id"] = frame.loc[0, "sample_id"]
    elif damage == "target":
        frame["target"] = 123456
    else:
        frame.loc[0, "prediction"] = np.inf
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError):
        evaluate(snapshot)
    assert not (tmp_path / "evaluation/matbench_result.shareable.json").exists()


def test_cache_drift_clears_stale_public_and_preserves_external_predictions(snapshot):
    root, task, path, tmp_path = snapshot
    output = tmp_path / "evaluation"
    output.mkdir()
    public = output / "matbench_result.shareable.json"
    public.write_text("stale")
    markdown = output / "matbench_result.md"
    markdown.write_text("stale")
    original = path.read_bytes()
    (root / task.filename).write_bytes(b"changed cache")
    with pytest.raises(ValueError):
        evaluate(snapshot)
    assert (
        not public.exists() and not markdown.exists() and path.read_bytes() == original
    )


def test_release_recomputes_folds_and_withholds_private_provenance(snapshot):
    result = evaluate(snapshot)
    artifact = result["artifact"]
    _, task, _, tmp_path = snapshot
    artifact["shareable"]["metrics"][task.metric] = 9999
    policy = {
        "schema_version": "release-policy/v1",
        "id": "synthetic-review",
        "enabled": True,
        "require_privacy_audit": False,
        "include_protocol": True,
        "public_benchmark": task.identity(),
    }
    decision, public = check_release(artifact, policy)
    assert decision.decision == "allow"
    assert public["shareable"]["metrics"][task.metric] != 9999
    text = json.dumps(public)
    assert (
        str(tmp_path) not in text
        and "prediction_sha256" not in text
        and "NeverInstantiate" not in text
    )
    policy["min_samples"] = 22
    assert check_release(artifact, policy)[1] is None


def test_cached_scoring_imports_no_optional_structure_framework(snapshot, monkeypatch):
    monkeypatch.setitem(sys.modules, "matbench", None)
    monkeypatch.setitem(sys.modules, "matminer", None)
    assert evaluate(snapshot)["artifact"]["shareable"]["input_type"] in {
        "composition",
        "structure",
    }


def test_fixed_predictions_match_the_pinned_upstream_evaluator(snapshot):
    pytest.importorskip("matbench")
    from matbench.data_ops import score_array
    import inspect

    assert (
        sha256(Path(inspect.getsourcefile(score_array)).read_bytes()).hexdigest()
        == matbench.REFERENCE_SCORER_SHA256
    )
    root, task, path, _ = snapshot
    loaded = matbench.load_snapshot(root, task.name)
    frames = matbench.align_predictions(loaded, path.read_bytes())
    artifact = evaluate(snapshot)["artifact"]
    for row, frame in zip(artifact["shareable"]["folds"], frames):
        expected = score_array(
            frame.target.to_numpy(), frame.prediction.to_numpy(), task.task_type
        )[task.upstream_metric]
        assert row["score"] == pytest.approx(expected, abs=1e-12)
    if task.task_type == "classification":
        actual = score_array([0, 0, 1, 1], [0.2, 0.1, 0.4, 0.3], "classification")[
            "rocauc"
        ]
        assert actual == 1.0


def test_unknown_tasks_do_not_receive_substituted_metrics(tmp_path):
    with pytest.raises(ValueError, match="unsupported"):
        matbench.load_snapshot(tmp_path, "unsupported_material_task")


def test_result_schema_and_private_unit_contract(snapshot):
    from jsonschema import Draft202012Validator
    from privatelabbench.reports.integrity import attach_integrity_metadata

    result = evaluate(snapshot)
    _, task, _, _ = snapshot
    directory = Path(matbench.__file__).parents[1] / "data/schemas"
    schema = json.loads((directory / "matbench-evaluation-v1.schema.json").read_text())
    validator = Draft202012Validator(schema)
    validator.validate(result["artifact"])
    policy = {
        "schema_version": "release-policy/v1",
        "id": "schema-review",
        "enabled": True,
        "require_privacy_audit": False,
        "include_protocol": True,
        "public_benchmark": task.identity(),
    }
    decision, public = check_release(result["artifact"], policy)
    assert decision.decision == "allow"
    validator.validate(attach_integrity_metadata(public))
    definition = resolve_protocol(task.protocol)
    assert definition.as_dict().get("target_unit") == task.unit
    changed = definition.as_dict()
    changed["target_unit"] = "different-unit"
    from privatelabbench.protocols import EvaluationProtocol

    assert EvaluationProtocol.from_dict(changed).sha256 != definition.sha256
