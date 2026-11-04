"""Preflight failures must preserve inputs, old outputs, and release state."""

from argparse import Namespace

import pytest

from privatelabbench.cli import audit_design_command, main
from privatelabbench.leaderboards import leaderboard_command
from privatelabbench.privacy.export import publish_shareable_artifact
from privatelabbench.reports.manifest import write_run_manifest
from privatelabbench.reports.paired_comparison import write_paired_comparison_artifacts
from privatelabbench.reports.receipt import write_evaluation_receipts
from privatelabbench.trends import trend_command


@pytest.mark.parametrize("reserved", [".plb-release-ledger.json", ".plb-release.lock"])
def test_export_cannot_replace_its_own_release_state(tmp_path, reserved):
    output = tmp_path / reserved
    output.write_bytes(b"existing release state")
    with pytest.raises(ValueError, match="Output paths"):
        publish_shareable_artifact({}, None, output)
    assert output.read_bytes() == b"existing release state"


def test_export_rejects_hardlinked_ledger_before_removing_anything(tmp_path):
    ledger = tmp_path / ".plb-release-ledger.json"
    ledger.write_bytes(b"existing release state")
    output = tmp_path / "public.json"
    output.hardlink_to(ledger)
    with pytest.raises(ValueError, match="Output paths"):
        publish_shareable_artifact({}, None, output)
    assert output.read_bytes() == ledger.read_bytes() == b"existing release state"


@pytest.mark.parametrize(
    "collision", ["duplicate", "input_hardlink", "ledger_hardlink"]
)
def test_receipt_writer_checks_all_paths_before_building_or_deleting(
    tmp_path, collision
):
    report, manifest, config = [
        tmp_path / name for name in ["report.json", "manifest.json", "config.yaml"]
    ]
    for path in (report, manifest, config):
        path.write_bytes(b"input sentinel")
    full, public, markdown = [
        tmp_path / name for name in ["receipt.json", "public.json", "receipt.md"]
    ]
    if collision == "duplicate":
        public = full
    elif collision == "input_hardlink":
        full.hardlink_to(report)
    else:
        ledger = tmp_path / ".plb-release-ledger.json"
        ledger.write_bytes(b"ledger sentinel")
        markdown.hardlink_to(ledger)
    for path in (full, public, markdown):
        if not path.exists():
            path.write_bytes(b"old output sentinel")
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError, match="Output paths"):
        write_evaluation_receipts(
            full_path=full,
            shareable_path=public,
            markdown_path=markdown,
            summary={},
            report_path=report,
            manifest_path=manifest,
            config_path=config,
        )
    assert {p: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_manifest_preflight_includes_derived_receipts(tmp_path):
    report = tmp_path / "report.json"
    report.write_bytes(b"input sentinel")
    output = tmp_path / "run_manifest.json"
    public = tmp_path / "run_receipt.shareable.json"
    public.hardlink_to(report)
    with pytest.raises(ValueError, match="Output paths"):
        write_run_manifest(
            output,
            summary={},
            config_path=tmp_path / "config.yaml",
            json_report_path=report,
            audit_log_path=tmp_path / "audit.jsonl",
        )
    assert not output.exists()
    assert public.read_bytes() == report.read_bytes() == b"input sentinel"


def test_paired_writer_rejects_duplicate_outputs_before_building(tmp_path):
    output = tmp_path / "comparison.json"
    output.write_bytes(b"old comparison")
    with pytest.raises(ValueError, match="Output paths"):
        write_paired_comparison_artifacts(
            json_path=output,
            markdown_path=output,
            result={},
            path_a=tmp_path / "a.csv",
            path_b=tmp_path / "b.csv",
        )
    assert output.read_bytes() == b"old comparison"


@pytest.mark.parametrize("command", [trend_command, leaderboard_command])
@pytest.mark.parametrize("collision", ["duplicate", "hardlink"])
def test_receipt_commands_reject_aliases_without_deleting_old_outputs(
    tmp_path, command, collision
):
    source = tmp_path / "source.json"
    source.write_bytes(b"input sentinel")
    output = tmp_path / ("result.md" if collision == "duplicate" else "result.json")
    output.write_bytes(b"old local output")
    public = output.with_name(output.stem + ".shareable.json")
    if collision == "hardlink":
        public.hardlink_to(source)
    else:
        public.write_bytes(b"old public output")
    args = Namespace(
        out=str(output),
        inputs=[str(source)],
        quality_policy=None,
        release_policy=None,
        trust_store=None,
        protocol="plb://generic/regression@1.0.0",
        signing_secret=None,
        require_trusted_signer=False,
        critical_slice=[],
        series="series@1",
        model="model@1",
        metric="rmse",
        time=["2026-01-01"],
        reference_index=0,
        practical_threshold=0.0,
        prevalence_threshold=0.0,
    )
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    assert command(args) == 2
    assert {p: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_design_audit_preserves_hardlinked_output_on_preflight_failure(tmp_path):
    source = tmp_path / "data.csv"
    source.write_bytes(b"input sentinel")
    output = tmp_path / "audit.json"
    output.hardlink_to(source)
    args = Namespace(
        out=str(output),
        evaluation=str(source),
        training_reference=None,
        protocol="plb://generic/regression@1.0.0",
        reference_complete=False,
    )
    assert audit_design_command(args) == 2
    assert source.read_bytes() == output.read_bytes() == b"input sentinel"


def test_init_force_cannot_overwrite_a_hardlinked_prediction_input(
    tmp_path, monkeypatch, capsys
):
    source = tmp_path / "data.csv"
    source.write_bytes(b"sample_id,target,prediction\na,1,1.1\nb,2,1.9\n")
    config = tmp_path / "config.yaml"
    config.hardlink_to(source)
    monkeypatch.setattr(
        "sys.argv",
        [
            "plb",
            "init",
            str(source),
            "--task-type",
            "regression",
            "--out",
            str(config),
            "--output-dir",
            str(tmp_path / "results"),
            "--force",
        ],
    )
    assert main() == 2
    assert "Output paths" in capsys.readouterr().out
    assert (
        source.read_bytes()
        == config.read_bytes()
        == b"sample_id,target,prediction\na,1,1.1\nb,2,1.9\n"
    )


def test_scoring_collision_preserves_model_units_and_stale_exports(tmp_path):
    from privatelabbench.scoring import score_command

    model = tmp_path / "model.yaml"
    model.write_bytes(b"{}")
    units = tmp_path / "units.yaml"
    units.write_bytes(b"{}")
    folder = tmp_path / "evaluation"
    folder.mkdir()
    public = folder / "evaluation_receipt.shareable.json"
    public.hardlink_to(units)
    markdown = folder / "evaluation_receipt.md"
    markdown.write_bytes(b"old export")
    args = Namespace(
        model=str(model),
        data=str(tmp_path / "data.csv"),
        units=str(units),
        release_policy=None,
        validation_profile=None,
        protocol="plb://generic/regression@1.0.0",
        output=str(tmp_path / "predictions.csv"),
        evaluate_output_dir=str(folder),
        target="target",
        data_version=None,
    )
    assert score_command(args) == 2
    assert units.read_bytes() == public.read_bytes() == b"{}"
    assert markdown.read_bytes() == b"old export"


def test_hidden_benchmark_preflight_preserves_hardlinked_owner_input(tmp_path):
    from privatelabbench.hidden_benchmarks import evaluate_benchmark

    spec = tmp_path / "owner.yaml"
    spec.write_bytes(b"{}")
    folder = tmp_path / "evaluation"
    folder.mkdir()
    public = folder / "evaluation_receipt.shareable.json"
    public.hardlink_to(spec)
    with pytest.raises(ValueError, match="Output paths"):
        evaluate_benchmark(
            spec,
            tmp_path / "predictions.csv",
            folder,
            submission_id="test",
            model="test@1",
        )
    assert spec.read_bytes() == public.read_bytes() == b"{}"
