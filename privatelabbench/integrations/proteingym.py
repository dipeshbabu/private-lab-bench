"""Pinned DMS substitution assays and receipt-native, assay-level Spearman scores."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json, os, re, tempfile, zipfile
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import yaml

from privatelabbench.aggregate import model_identity
from privatelabbench.core.local_io import atomic_write_csv
from privatelabbench.core.public_data import download_verified
from privatelabbench.privacy.export import (
    _mapping,
    atomic_write_json,
    protocol_identity,
)
from privatelabbench.protocols import resolve_protocol
from privatelabbench.reports.integrity import attach_integrity_metadata

REGISTRY = json.loads(
    (Path(__file__).parents[1] / "data/integrations/proteingym-assays.json").read_text()
)
REFERENCE_COMMIT = REGISTRY["reference_commit"]
REFERENCE_SHA256 = REGISTRY["reference_sha256"]
ARCHIVE_SHA256 = REGISTRY["archive_sha256"]
ARCHIVE_NAME = "DMS_ProteinGym_substitutions-v1.3.zip"
REFERENCE_FILE = "DMS_substitutions.csv"
BENCHMARK_VERSION = "proteingym-v1.3-3a837662-144fe22b"
PROTOCOL = "plb://proteingym/dms-substitutions-spearman@1.0.0"
RESULT_SCHEMA = "proteingym-evaluation/v1"


@dataclass(frozen=True)
class DMSAssay:
    id: str
    filename: str
    sha256: str
    uniprot_id: str
    function: str
    taxon: str
    n_variants: int


ASSAYS = {record["id"]: DMSAssay(**record) for record in REGISTRY["assays"]}


def selected_assays(names):
    if (
        not isinstance(names, (list, tuple))
        or not names
        or len(set(names)) != len(names)
    ):
        raise ValueError("Explicit unique assay IDs are required")
    if not set(names) <= set(ASSAYS):
        raise ValueError(
            "Unsupported assay; use the pinned DMS substitution subset or the ordinary private-data protocol"
        )
    return tuple(ASSAYS[name] for name in sorted(names))


def benchmark_identity():
    return {
        "id": "proteingym-dms-substitutions",
        "version": BENCHMARK_VERSION,
        "suite": "proteingym",
        "domain": "proteins",
        "protocol": "prediction-table/v1",
    }


def _verified(path, expected):
    content = Path(path).read_bytes()
    if sha256(content).hexdigest() != expected:
        raise ValueError(
            "ProteinGym snapshot differs from pinned official bytes; modified/private data needs the ordinary protocol"
        )
    return content


def _write_snapshot(path, body, expected):
    path = Path(path)
    if sha256(body).hexdigest() != expected:
        raise ValueError("Extracted assay differs from its pinned digest")
    if path.exists():
        _verified(path, expected)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".plb-assay-", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(body)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def download_assays(root, names):
    assays = selected_assays(names)
    root = Path(root).resolve()
    download_verified(
        root / REFERENCE_FILE,
        f"https://raw.githubusercontent.com/OATML-Markslab/ProteinGym/{REFERENCE_COMMIT}/reference_files/{REFERENCE_FILE}",
        REFERENCE_SHA256,
    )
    download_verified(root / ARCHIVE_NAME, REGISTRY["archive_url"], ARCHIVE_SHA256)
    content = _verified(root / ARCHIVE_NAME, ARCHIVE_SHA256)
    with zipfile.ZipFile(BytesIO(content)) as archive:
        for assay in assays:
            member = f"DMS_ProteinGym_substitutions/{assay.filename}"
            if archive.getinfo(member).file_size > 32 * 1024 * 1024:
                raise ValueError("Pinned assay exceeds the extraction limit")
            _write_snapshot(root / assay.filename, archive.read(member), assay.sha256)


@dataclass(frozen=True)
class AssaySnapshot:
    assay: DMSAssay
    frame: pd.DataFrame = field(repr=False, compare=False)


def load_assay(root, name):
    assay = selected_assays([name])[0]
    root = Path(root).resolve()
    reference = pd.read_csv(
        BytesIO(_verified(root / REFERENCE_FILE, REFERENCE_SHA256)),
        dtype={"DMS_id": "string"},
    )
    metadata = reference[reference.DMS_id == name]
    if len(metadata) != 1:
        raise ValueError("Assay metadata identity is missing or duplicated")
    row = metadata.iloc[0]
    if (
        row["UniProt_ID"] != assay.uniprot_id
        or row["coarse_selection_type"] != assay.function
        or row["taxon"] != assay.taxon
        or row["DMS_filename"] != assay.filename
        or int(row["DMS_total_number_mutants"]) != assay.n_variants
    ):
        raise ValueError("Pinned assay grouping/record metadata differs")
    body = _verified(root / assay.filename, assay.sha256)
    frame = pd.read_csv(
        BytesIO(body), usecols=["mutant", "DMS_score"], dtype={"mutant": "string"}
    )
    if (
        len(frame) != assay.n_variants
        or frame.mutant.isna().any()
        or frame.mutant.str.strip().eq("").any()
        or frame.mutant.duplicated().any()
    ):
        raise ValueError(
            "Every official variant must have its unique recorded identity"
        )
    targets = pd.to_numeric(frame.DMS_score, errors="raise").to_numpy(dtype=float)
    if not np.isfinite(targets).all():
        raise ValueError("Official DMS scores must be finite; no variants are dropped")
    result = pd.DataFrame(
        {
            "sample_id": [f"{assay.id}:{mutant}" for mutant in frame.mutant],
            "mutant": frame.mutant.to_numpy(),
            "target": targets,
            "assay": assay.id,
        }
    )
    return AssaySnapshot(assay, result)


def prepare_template(root, names, output, *, download=False):
    assays = selected_assays(names)
    if download:
        download_assays(root, names)
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Choose a fresh ProteinGym prediction-template path")
    tables = []
    for assay in assays:
        frame = load_assay(root, assay.id).frame[["assay", "sample_id"]].copy()
        frame["prediction"] = np.nan
        tables.append(frame)
    atomic_write_csv(output, pd.concat(tables, ignore_index=True))
    return {
        "assays": len(assays),
        "variants": sum(assay.n_variants for assay in assays),
        "template": str(output),
    }


def align_predictions(snapshots, content, prediction_column, score_direction):
    if score_direction not in {"higher", "lower"}:
        raise ValueError(
            "Declare whether higher or lower model scores predict higher fitness"
        )
    if prediction_column in {
        "DMS_score",
        "DMS_score_bin",
        "target",
        "sample_id",
        "assay",
        "mutant",
        "mutated_sequence",
    }:
        raise ValueError(
            "Select a model-score column, separate from labels, IDs, and sequences"
        )
    source = pd.read_csv(
        BytesIO(content),
        dtype={"sample_id": "string", "mutant": "string", "assay": "string"},
    )
    names = {snapshot.assay.id for snapshot in snapshots}
    if prediction_column not in source:
        raise ValueError("The declared model-score column is missing")
    if "assay" not in source:
        if len(names) != 1:
            raise ValueError(
                "Multiple assays require explicit assay identity on every row"
            )
        source["assay"] = next(iter(names))
    if source.assay.isna().any() or set(source.assay) != names:
        raise ValueError(
            "Prediction assay coverage differs from the explicitly selected set"
        )
    if "sample_id" not in source:
        if "mutant" not in source or source.mutant.isna().any():
            raise ValueError(
                "Provide stable sample_id values or ProteinGym mutant descriptors"
            )
        source["sample_id"] = source.assay + ":" + source.mutant
    elif (
        "mutant" in source
        and not (source.sample_id == source.assay + ":" + source.mutant).all()
    ):
        raise ValueError("Variant descriptors contradict stable sample IDs")
    if source.sample_id.isna().any() or source.sample_id.duplicated().any():
        raise ValueError("Stable variant IDs must be complete and unique")
    frames = []
    for snapshot in snapshots:
        expected = snapshot.frame
        rows = source[source.assay == snapshot.assay.id]
        if set(rows.sample_id) != set(expected.sample_id):
            raise ValueError(
                "Predictions must exactly cover every official variant in each assay"
            )
        aligned = rows.set_index("sample_id").loc[expected.sample_id]
        for target_column in ("target", "DMS_score"):
            if target_column in aligned and not np.allclose(
                pd.to_numeric(aligned[target_column], errors="raise").to_numpy(
                    dtype=float
                ),
                expected.target.to_numpy(dtype=float),
                rtol=0,
                atol=1e-12,
            ):
                raise ValueError(
                    "Provided target values disagree with the pinned processed DMS scores"
                )
        scores = pd.to_numeric(aligned[prediction_column], errors="raise").to_numpy(
            dtype=float
        )
        if not np.isfinite(scores).all():
            raise ValueError("Model scores must be finite for every variant")
        frame = expected[["sample_id", "target", "assay"]].copy()
        frame["prediction"] = scores if score_direction == "higher" else -scores
        frames.append(frame)
    return tuple(frames)


def _score(value):
    return (
        float(value)
        if type(value) in {float, int} and np.isfinite(value) and -1 <= value <= 1
        else None
    )


def _mean(values):
    return (
        float(np.mean(values))
        if values and all(value is not None for value in values)
        else None
    )


def summarize_assays(rows):
    rows = [
        {
            **row,
            "aggregation_spearman": (
                float(np.round(row["spearman"], 3))
                if row["spearman"] is not None
                else None
            ),
        }
        for row in rows
    ]
    groups = {}
    taxa = {}
    for row in rows:
        groups.setdefault((row["uniprot_id"], row["function"]), []).append(
            row["aggregation_spearman"]
        )
        taxa.setdefault((row["uniprot_id"], row["taxon"]), []).append(
            row["aggregation_spearman"]
        )
    proteins = [
        {
            "uniprot_id": protein,
            "function": function,
            "n_assays": len(scores),
            "spearman": _mean(scores),
        }
        for (protein, function), scores in sorted(groups.items())
    ]
    functions = []
    for function in sorted({row["function"] for row in proteins}):
        values = [row["spearman"] for row in proteins if row["function"] == function]
        functions.append(
            {"function": function, "n_proteins": len(values), "spearman": _mean(values)}
        )
    taxon_rows = []
    for taxon in sorted({key[1] for key in taxa}):
        values = [
            _mean(scores)
            for (protein, label), scores in sorted(taxa.items())
            if label == taxon
        ]
        taxon_rows.append(
            {"taxon": taxon, "n_proteins": len(values), "spearman": _mean(values)}
        )
    overall = _mean([row["spearman"] for row in functions])
    return {
        "per_assay": rows,
        "per_protein_function": proteins,
        "per_function": functions,
        "per_taxon": taxon_rows,
        "metrics": {"spearman": overall},
        "status": "evaluated" if overall is not None else "undefined_assay_score",
        "aggregation": "mean_assays_within_protein_function_then_mean_proteins_within_function_then_mean_functions",
        "aggregation_precision": "assay_scores_rounded_to_3_decimals_before_grouping",
        "uncertainty_scope": "point_estimates_no_aggregate_bootstrap",
        "benchmark_scope": "selected_assay_subset",
        "full_benchmark_assay_count": REGISTRY["full_assay_count"],
    }


def evaluate_proteingym(
    root,
    names,
    predictions,
    output_dir,
    *,
    model,
    score_direction,
    prediction_column="prediction",
    release_policy_path=None,
):
    from privatelabbench.runner import run_config
    from privatelabbench.privacy.export import publish_shareable_artifact

    output = Path(output_dir).resolve()
    result_path, public, markdown = (
        output / name
        for name in (
            "proteingym_result.json",
            "proteingym_result.shareable.json",
            "proteingym_result.md",
        )
    )
    protected = {
        Path(predictions).resolve(),
        Path(root).resolve() / ARCHIVE_NAME,
        Path(root).resolve() / REFERENCE_FILE,
        *[Path(root).resolve() / assay.filename for assay in ASSAYS.values()],
    }
    if release_policy_path:
        protected.add(Path(release_policy_path).resolve())
    targets = {
        result_path,
        public,
        markdown,
        public.with_suffix(".release-audit.json"),
        output / ".plb-release-ledger.json",
        output / ".plb-release.lock",
    }
    for assay in ASSAYS.values():
        targets.update(
            output / assay.id / name
            for name in (
                "predictions.csv",
                "evaluation.yaml",
                "evaluation.json",
                "evaluation.md",
                "evaluation_manifest.json",
                "evaluation_receipt.json",
                "evaluation_receipt.shareable.json",
                "evaluation_receipt.md",
                "audit.jsonl",
                "evaluation_receipt.shareable.release-audit.json",
                ".plb-release-ledger.json",
                ".plb-release.lock",
            )
        )
    if targets & protected:
        raise ValueError(
            "ProteinGym outputs must preserve every cache, score, and policy input"
        )
    public.unlink(missing_ok=True)
    markdown.unlink(missing_ok=True)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose an empty ProteinGym evaluation directory")
    assays = selected_assays(names)
    if isinstance(model, str):
        if "@" not in model:
            raise ValueError("Model identity requires id@revision")
        name, revision = model.rsplit("@", 1)
        model = {"id": name, "revision": revision}
    model = model_identity(model)
    policy = (
        yaml.safe_load(Path(release_policy_path).read_text(encoding="utf-8"))
        if release_policy_path
        else None
    )
    snapshots = tuple(load_assay(root, assay.id) for assay in assays)
    content = Path(predictions).read_bytes()
    frames = align_predictions(snapshots, content, prediction_column, score_direction)
    rows = []
    receipts = []
    for snapshot, frame in zip(snapshots, frames):
        assay = snapshot.assay
        folder = output / assay.id
        table = folder / "predictions.csv"
        atomic_write_csv(table, frame)
        settings = {
            "project": assay.id,
            "protocol": PROTOCOL,
            "benchmark": {**benchmark_identity(), "id": assay.id},
            "input": {
                "path": str(table),
                "sample_id_column": "sample_id",
                "target_column": "target",
                "prediction_column": "prediction",
                "slice_columns": ["assay"],
            },
            "report": {
                "json": str(folder / "evaluation.json"),
                "markdown": str(folder / "evaluation.md"),
                "manifest": str(folder / "evaluation_manifest.json"),
            },
            "audit": {"path": str(folder / "audit.jsonl")},
            "proteingym_local": {
                "assay": assay.id,
                "uniprot_id": assay.uniprot_id,
                "function": assay.function,
                "taxon": assay.taxon,
                "data_sha256": assay.sha256,
                "reference_commit": REFERENCE_COMMIT,
                "model": model,
                "original_score_direction": score_direction,
            },
        }
        config = folder / "evaluation.yaml"
        config.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")
        result = run_config(str(config))
        point = _score(result["reported_metrics"]["spearman"])
        rows.append(
            {
                "assay": assay.id,
                "uniprot_id": assay.uniprot_id,
                "function": assay.function,
                "taxon": assay.taxon,
                "n_variants": len(frame),
                "spearman": point,
            }
        )
        receipt = folder / "evaluation_receipt.json"
        receipts.append(
            {
                "assay": assay.id,
                "path": str(receipt),
                "payload_sha256": json.loads(receipt.read_text())["integrity"][
                    "payload_sha256"
                ],
            }
        )
    shared = {
        "benchmark": benchmark_identity(),
        "protocol": resolve_protocol(PROTOCOL).identity(),
        "model": model,
        "original_score_direction": score_direction,
        "per_assay": rows,
        **summarize_assays(rows),
        "reference_commit": REFERENCE_COMMIT,
    }
    artifact = attach_integrity_metadata(
        {
            "schema_version": RESULT_SCHEMA,
            "evaluation_id": str(uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "scope": "local",
            "shareable": shared,
            "local": {
                "prediction_source": str(Path(predictions).resolve()),
                "prediction_column": prediction_column,
                "prediction_sha256": sha256(content).hexdigest(),
                "reference_file_sha256": REFERENCE_SHA256,
                "archive_sha256": ARCHIVE_SHA256,
                "assay_receipts": receipts,
                "protocol_definition": resolve_protocol(PROTOCOL).as_dict(),
            },
        }
    )
    atomic_write_json(result_path, artifact)
    decision = publish_shareable_artifact(artifact, policy, public)
    if decision.decision == "allow":
        markdown.write_text(
            render_result(json.loads(public.read_text(encoding="utf-8"))),
            encoding="utf-8",
        )
    return {
        "artifact": artifact,
        "local_result": str(result_path),
        "release": decision.as_dict(),
        "shareable_result": str(public) if decision.decision == "allow" else None,
    }


def sanitize_result(value, policy):
    shared = _mapping(value)
    definition = resolve_protocol(PROTOCOL)
    if (
        shared.get("benchmark") != benchmark_identity()
        or policy.get("public_benchmark") != benchmark_identity()
        or protocol_identity(shared.get("protocol")) != definition.identity()
        or not policy.get("include_protocol")
        or shared.get("reference_commit") != REFERENCE_COMMIT
    ):
        raise ValueError("Approve the exact ProteinGym snapshot/protocol identities")
    model = model_identity(shared.get("model"))
    if model not in [model_identity(item) for item in policy.get("public_models", [])]:
        raise ValueError("Approve the declared model identity")
    direction = shared.get("original_score_direction")
    if direction not in {"higher", "lower"}:
        raise ValueError("Explicit model-score direction is required")
    values = shared.get("per_assay")
    if not isinstance(values, list) or not values or len(values) > len(ASSAYS):
        raise ValueError("A nonempty pinned assay subset is required")
    rows = []
    seen = set()
    minimum = max(
        policy["min_samples"],
        policy["min_cell_size"],
        definition.as_dict()["release"]["min_samples"],
        definition.as_dict()["release"]["min_cell_size"],
    )
    for row in values:
        row = _mapping(row)
        assay = selected_assays([row.get("assay")])[0]
        if assay.id in seen or assay.id not in policy.get("public_assays", []):
            raise ValueError("Approve every unique assay identity")
        if row.get("n_variants") != assay.n_variants or assay.n_variants < minimum:
            raise ValueError("Every assay must satisfy release counts")
        score = row.get("spearman")
        if score is not None and _score(score) is None:
            raise ValueError("Invalid assay Spearman coefficient")
        seen.add(assay.id)
        rows.append(
            {
                "assay": assay.id,
                "uniprot_id": assay.uniprot_id,
                "function": assay.function,
                "taxon": assay.taxon,
                "n_variants": assay.n_variants,
                "spearman": _score(score),
            }
        )
    rows.sort(key=lambda row: row["assay"])
    return {
        "benchmark": benchmark_identity(),
        "protocol": definition.identity(),
        "model": model,
        "original_score_direction": direction,
        "per_assay": rows,
        **summarize_assays(rows),
        "reference_commit": REFERENCE_COMMIT,
    }


def render_result(artifact):
    shared = artifact["shareable"]
    lines = [
        "# ProteinGym DMS substitution evaluation",
        "",
        f"Model: {shared['model']['id']}@{shared['model']['revision']}; scope: selected assay subset.",
        "",
        "| Assay | Protein | Function | Taxon | N | Spearman |",
        "| --- | --- | --- | --- | ---: | ---: |",
    ]
    for row in shared["per_assay"]:
        point = f"{row['spearman']:.6g}" if row["spearman"] is not None else "undefined"
        lines.append(
            f"| {row['assay']} | {row['uniprot_id']} | {row['function']} | {row['taxon']} | {row['n_variants']} | {point} |"
        )
    point = shared["metrics"]["spearman"]
    lines.extend(
        [
            "",
            (
                f"Selected-subset hierarchical mean: {point:.6g}."
                if point is not None
                else "Hierarchical mean unavailable because an assay score is undefined."
            ),
            "Assays are averaged within protein/function, then proteins within function, then functions equally. Variants from different assays are never pooled. This subset is not a full ProteinGym leaderboard result; no aggregate uncertainty or clinical validity is claimed.",
        ]
    )
    return "\n".join(lines) + "\n"


def proteingym_command(args):
    try:
        if args.command == "proteingym-list":
            for name in sorted(ASSAYS):
                assay = ASSAYS[name]
                print(
                    f"{name}: {assay.n_variants} variants; {assay.function}; {assay.taxon}"
                )
        elif args.command == "proteingym-prepare":
            result = prepare_template(
                args.cache_dir, args.assay, args.out, download=args.download
            )
            print(
                f"ProteinGym template: {result['template']}; {result['assays']} assays, {result['variants']} variants"
            )
        else:
            result = evaluate_proteingym(
                args.cache_dir,
                args.assay,
                args.predictions,
                args.output_dir,
                model=args.model,
                score_direction=args.score_direction,
                prediction_column=args.prediction_column,
                release_policy_path=args.release_policy,
            )
            print(f"Local ProteinGym result: {result['local_result']}")
            print(
                f"Selected-subset hierarchical Spearman: {result['artifact']['shareable']['metrics']['spearman']}; release: {result['release']['decision']}"
            )
        return 0
    except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError):
        print(
            "ProteinGym workflow rejected. Check the pinned assays/cache, complete variant coverage, explicit model/score direction, and fresh output paths."
        )
        return 2
