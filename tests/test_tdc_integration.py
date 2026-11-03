"""Synthetic contract cases; real upstream parity is an explicit opt-in script."""

from dataclasses import replace
from hashlib import sha256
import json

import numpy as np
import pandas as pd
import pytest

from privatelabbench.cli import main
from privatelabbench.integrations import tdc
from privatelabbench.reports.receipt import verify_receipt


@pytest.fixture(params=["caco2_wang", "pgp_broccatelli"])
def snapshot(tmp_path, monkeypatch, request):
    """Checksums are patched only for explicitly synthetic, data-free CI cases."""
    name = request.param
    task = tdc.TASKS[name]
    root = tmp_path / "cache"
    folder = root / "admet_group" / name
    folder.mkdir(parents=True)
    hashes = {}
    for partition, n in (("train_val", 32), ("test", 24)):
        frame = pd.DataFrame(
            {
                "Drug_ID": ["repeated-upstream-id"] * n,
                "Drug": ["CCO"] * n,
                "Y": [
                    i % 2 if task.task_type == "classification" else i / 7
                    for i in range(n)
                ],
            }
        )
        path = folder / f"{partition}.csv"
        frame.to_csv(path, index=False)
        hashes[partition + "_sha256"] = sha256(path.read_bytes()).hexdigest()
    monkeypatch.setitem(tdc.TASKS, name, replace(task, **hashes))
    monkeypatch.setattr(tdc, "BENCHMARK_VERSION", "synthetic-contract-fixture")
    return root, name, tmp_path


def prediction_file(snapshot):
    root, name, tmp_path = snapshot
    benchmark = tdc.load_benchmark(root, name)
    frame = tdc.partition_table(benchmark.test, benchmark.task, "test")
    frame["prediction"] = np.linspace(0.05, 0.95, len(frame))
    path = tmp_path / "external.csv"
    frame[["sample_id", "prediction"]].to_csv(path, index=False)
    return benchmark, frame, path


def test_fixed_records_preserve_duplicates_and_template_contains_no_targets(snapshot):
    root, name, tmp_path = snapshot
    benchmark, frame, _ = prediction_file(snapshot)
    assert len(frame) == len(benchmark.test) == 24
    assert frame.sample_id.is_unique and frame.upstream_drug_id.nunique() == 1
    template = tmp_path / "template.csv"
    result = tdc.prepare_template(root, name.upper(), template)
    assert result["protocol"] == benchmark.task.protocol
    assert list(pd.read_csv(template)) == ["sample_id", "prediction"]
    assert "target" not in template.read_text() and "CCO" not in template.read_text()
    with pytest.raises(ValueError, match="already exists"):
        tdc.prepare_template(root, name, template)


def test_shuffled_exact_ids_align_and_idless_order_requires_declaration(snapshot):
    benchmark, expected, path = prediction_file(snapshot)
    expected.sample(frac=1, random_state=17).to_csv(path, index=False)
    pd.testing.assert_frame_equal(tdc.align_predictions(benchmark, path), expected)
    expected[["prediction"]].to_csv(path, index=False)
    with pytest.raises(ValueError, match="explicitly declare"):
        tdc.align_predictions(benchmark, path)
    pd.testing.assert_frame_equal(
        tdc.align_predictions(benchmark, path, upstream_test_order=True), expected
    )


@pytest.mark.parametrize(
    "damage", ["duplicate", "missing", "unknown", "target", "nonfinite"]
)
def test_invalid_submission_rejected(snapshot, damage):
    benchmark, frame, path = prediction_file(snapshot)
    if damage == "duplicate":
        frame.loc[1, "sample_id"] = frame.loc[0, "sample_id"]
    elif damage == "missing":
        frame = frame.iloc[:-1]
    elif damage == "unknown":
        frame.loc[0, "sample_id"] = "not-an-official-record"
    elif damage == "target":
        frame.loc[0, "target"] = 123
    else:
        frame.loc[0, "prediction"] = float("inf")
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError):
        tdc.align_predictions(benchmark, path)


def test_binary_profile_rejects_out_of_range_scores(tmp_path):
    task = tdc.TASKS["pgp_broccatelli"]
    raw = pd.DataFrame({"Drug_ID": ["a", "b"], "Drug": ["C", "CC"], "Y": [0, 1]})
    with pytest.raises(ValueError, match="probabilities"):
        tdc.partition_table(raw, task, "test", predictions=[-1, 2])


def test_receipt_identity_default_local_and_failed_snapshot_removes_stale_public(
    snapshot,
):
    root, name, tmp_path = snapshot
    benchmark, _, predictions = prediction_file(snapshot)
    output = tmp_path / "result"
    summary = tdc.evaluate_tdc(root, name, predictions, output)
    assert benchmark.task.metric in summary["reported_metrics"]
    receipt = output / "evaluation_receipt.json"
    assert verify_receipt(receipt)["valid"]
    payload = json.loads(receipt.read_text())
    evaluation = payload["shareable"]["evaluation"]
    assert evaluation["protocol"]["metrics"] == [benchmark.task.metric]
    assert (
        evaluation["protocol"]["id"] + "@" + evaluation["protocol"]["version"]
        == benchmark.task.protocol
    )
    assert payload["shareable"]["benchmark"]["version"] == "synthetic-contract-fixture"
    assert not (output / "evaluation_receipt.shareable.json").exists()
    public = output / "evaluation_receipt.shareable.json"
    markdown = output / "evaluation_receipt.md"
    public.write_text("stale public result")
    markdown.write_text("stale public summary")
    (benchmark.root / "test.csv").write_text("changed upstream snapshot")
    with pytest.raises(ValueError, match="silent data drift"):
        tdc.evaluate_tdc(root, name, predictions, output)
    assert not public.exists() and not markdown.exists()


def test_protect_input_and_manual_config(snapshot):
    root, name, tmp_path = snapshot
    _, _, predictions = prediction_file(snapshot)
    output = tmp_path / "result"
    output.mkdir()
    manual = output / "evaluation.yaml"
    manual.write_text("# manual configuration\n")
    with pytest.raises(ValueError, match="manually authored"):
        tdc.evaluate_tdc(root, name, predictions, output)
    assert manual.read_text() == "# manual configuration\n"
    public = output / "evaluation_receipt.shareable.json"
    public.write_bytes(predictions.read_bytes())
    before = public.read_bytes()
    with pytest.raises(ValueError, match="separate"):
        tdc.evaluate_tdc(root, name, public, output)
    assert public.read_bytes() == before


def test_cli_local_run(snapshot, monkeypatch, capsys):
    root, name, tmp_path = snapshot
    _, _, predictions = prediction_file(snapshot)
    monkeypatch.setattr(
        "sys.argv",
        [
            "plb",
            "tdc-evaluate",
            str(predictions),
            "--dataset",
            name,
            "--cache-dir",
            str(root),
            "--output-dir",
            str(tmp_path / "cli"),
        ],
    )
    assert main() == 0
    assert "Official TDC primary metric" in capsys.readouterr().out


def test_unsupported_task_never_substitutes_metric(tmp_path):
    with pytest.raises(ValueError, match="unsupported official metrics"):
        tdc.load_benchmark(tmp_path, "unsupported-auprc-task")


def test_bad_policy_removes_stale_public_and_policy_input_is_protected(snapshot):
    root, name, tmp_path = snapshot
    _, _, predictions = prediction_file(snapshot)
    output = tmp_path / "policy-result"
    output.mkdir()
    public = output / "evaluation_receipt.shareable.json"
    public.write_text("stale result")
    policy = tmp_path / "invalid.yaml"
    policy.write_text("[]")
    with pytest.raises(ValueError, match="mapping"):
        tdc.evaluate_tdc(root, name, predictions, output, release_policy_path=policy)
    assert not public.exists()
    policy = output / "audit.jsonl"
    policy.write_text("schema_version: release-policy/v1\n")
    with pytest.raises(ValueError, match="separate"):
        tdc.evaluate_tdc(root, name, predictions, output, release_policy_path=policy)
    assert policy.read_text().startswith("schema_version:")


def test_fixed_prediction_metrics_match_optional_upstream(snapshot):
    upstream = pytest.importorskip("tdc")
    root, name, tmp_path = snapshot
    benchmark, frame, predictions = prediction_file(snapshot)
    result = tdc.evaluate_tdc(root, name, predictions, tmp_path / "parity")
    expected = upstream.Evaluator(name=benchmark.task.upstream_metric)(
        frame.target.to_numpy(), frame.prediction.to_numpy()
    )
    assert result["reported_metrics"][benchmark.task.metric] == pytest.approx(
        expected, abs=1e-12
    )
