from __future__ import annotations

import json
from pathlib import Path

import pytest

from privatelabbench.benchmark_packs import (
    PACK_SCHEMA_VERSION,
    discover_benchmark_packs,
    get_benchmark_pack,
    load_benchmark_pack,
    run_benchmark_pack,
)
from privatelabbench.reports.receipt import verify_receipt


EXPECTED_REFS = {
    "community-molecules-regression@1.0.0",
    "community-tabular-regression@1.0.0",
    "community-proteins-binary@1.0.0",
}


def _generated_shareable_receipt(summary: dict[str, object]) -> Path:
    manifest = Path(str(summary["manifest"]))
    stem = manifest.stem
    base = stem[: -len("_manifest")] if stem.endswith("_manifest") else stem
    return manifest.with_name(f"{base}_receipt.shareable.json")


def test_builtin_benchmark_packs_are_discoverable_and_valid():
    packs = discover_benchmark_packs()
    assert {pack.ref for pack in packs} == EXPECTED_REFS
    assert all(pack.license == "CC0-1.0" for pack in packs)
    assert all(pack.provenance["type"] == "synthetic" for pack in packs)
    assert {pack.domain for pack in packs} == {"molecules", "tabular", "proteins"}


def test_pack_lookup_supports_unique_id_and_explicit_ref():
    by_id = get_benchmark_pack("community-proteins-binary")
    by_ref = get_benchmark_pack("community-proteins-binary@1.0.0")
    assert by_id == by_ref
    assert by_ref.task == "predictions"


@pytest.mark.parametrize("pack_ref", sorted(EXPECTED_REFS))
def test_known_good_pack_receipts_are_valid(pack_ref):
    pack = get_benchmark_pack(pack_ref)
    result = verify_receipt(pack.expected_receipt_path)
    assert result["valid"] is True
    payload = json.loads(pack.expected_receipt_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "evaluation-receipt/v1"
    assert payload["scope"] == "shareable"
    assert payload["shareable"]["benchmark"]["id"] == pack.id
    assert payload["shareable"]["benchmark"]["version"] == pack.version


@pytest.mark.parametrize("pack_ref", sorted(EXPECTED_REFS))
def test_pack_runs_match_known_good_receipt_semantics(pack_ref):
    pack = get_benchmark_pack(pack_ref)
    expected = json.loads(pack.expected_receipt_path.read_text(encoding="utf-8"))["shareable"]
    summary = run_benchmark_pack(pack_ref)
    generated_path = _generated_shareable_receipt(summary)
    assert generated_path.exists()
    generated = json.loads(generated_path.read_text(encoding="utf-8"))["shareable"]

    assert summary["benchmark_pack"] == pack.ref
    assert generated["benchmark"] == expected["benchmark"]
    assert generated["evaluation"]["task_type"] == expected["evaluation"]["task_type"]
    assert generated["evaluation"]["sample_counts"] == expected["evaluation"]["sample_counts"]
    assert generated["evaluation"]["input_schema"] == expected["evaluation"]["input_schema"]
    assert generated["evaluation"]["metrics"] == pytest.approx(expected["evaluation"]["metrics"])
    assert generated["evaluation"]["slices"]


def test_protein_pack_is_self_contained_synthetic_data():
    pack = get_benchmark_pack("community-proteins-binary")
    text = pack.predictions_path.read_text(encoding="utf-8")
    assert "sequence" in text.splitlines()[0]
    assert "prot001" in text
    assert pack.provenance["derived_from"] == "none"


def test_pack_loader_rejects_metadata_config_mismatch(tmp_path):
    pack_dir = tmp_path / "bad"
    pack_dir.mkdir()
    (pack_dir / "predictions.csv").write_text("sample_id,target,prediction\na,0.1,0.1\n", encoding="utf-8")
    (pack_dir / "expected_receipt.json").write_text("{}\n", encoding="utf-8")
    (pack_dir / "config.yaml").write_text(
        """
project: bad
task: predictions
benchmark:
  id: actual-id
  version: "1.0.0"
  domain: tabular
input:
  path: predictions.csv
  target_column: target
  prediction_column: prediction
privacy:
  mode: none
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (pack_dir / "pack.yaml").write_text(
        f"""
schema_version: {PACK_SCHEMA_VERSION}
id: different-id
version: "1.0.0"
task: predictions
domain: tabular
description: invalid fixture
license: CC0-1.0
provenance:
  type: synthetic
files:
  config: config.yaml
  predictions: predictions.csv
  expected_receipt: expected_receipt.json
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="pack id must match"):
        load_benchmark_pack(pack_dir)
