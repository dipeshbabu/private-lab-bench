from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import yaml

from privatelabbench.benchmark_packs import discover_benchmark_packs, run_benchmark_pack
from privatelabbench.compare import compare_configs, compare_prediction_files
from privatelabbench.core.registry import discover_entrypoint_tasks, list_tasks
from privatelabbench.eval.metrics import summarize_metrics
from privatelabbench.eval.predictions import evaluate_prediction_csv
from privatelabbench.federated.evaluator import evaluate_federated_directory
from privatelabbench.models.sklearn_baseline import evaluate_random_forest
from privatelabbench.privacy.attacks import ensure_builtin_privacy_attacks_registered
from privatelabbench.privacy.attack_registry import list_privacy_attacks
from privatelabbench.privacy.dp import PrivacyConfig, privatize_metrics, privacy_summary
from privatelabbench.privacy.export import check_release, publish_shareable_artifact
from privatelabbench.quality import EXIT_CODES as QUALITY_EXIT_CODES, evaluate_quality_gate
from privatelabbench.reports.integrity import verify_report
from privatelabbench.reports.manifest import verify_run_manifest
from privatelabbench.reports.json import write_json_report
from privatelabbench.reports.markdown import write_federated_markdown_report, write_markdown_report, write_prediction_markdown_report
from privatelabbench.reports.receipt import RECEIPT_SCHEMA_VERSION, verify_receipt
from privatelabbench.runner import ensure_builtin_tasks_registered, print_run_summary, run_config
from privatelabbench.tasks.molecules import load_molecule_csv
from privatelabbench.validation import ConfigValidationResult, validate_config


def add_privacy_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument(
        "--privacy",
        choices=["none", "metric_perturbation", "dp"],
        default="none",
        help=(
            "Aggregate metric release mode. 'metric_perturbation' is heuristic Laplace noise with no formal DP guarantee; "
            "'dp' is a deprecated compatibility alias for the same heuristic mode."
        ),
    )
    parser.add_argument("--epsilon", type=float, default=8.0, help="Epsilon-like noise parameter for metric_perturbation.")
    parser.add_argument("--sensitivity", type=float, default=1.0, help="User-supplied noise-scale sensitivity for metric_perturbation; not framework-verified global sensitivity.")


def add_common_eval_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", required=True, help="Target column name.")
    parser.add_argument("--smiles-column", default="smiles", help="SMILES column name. Default: smiles")
    parser.add_argument("--task-type", choices=["regression", "classification"], default=None)
    parser.add_argument("--test-size", type=float, default=0.25)
    add_privacy_args(parser)


def add_simple_prediction_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("predictions", help="Local CSV with sample_id, target, and prediction columns, or explicit bindings.")
    parser.add_argument("--target", default=None)
    predictions = parser.add_mutually_exclusive_group()
    predictions.add_argument("--prediction-column", default=None)
    predictions.add_argument("--prediction-columns", nargs="+", default=None)
    parser.add_argument("--sample-id-column", default=None)
    parser.add_argument("--task-type", choices=["regression", "classification", "multiclass"], default=None)
    parser.add_argument("--class-labels", nargs="+", default=None, help="Ordered negative/positive labels, or multiclass labels matching probability columns.")
    parser.add_argument("--slice", action="append", default=None, help="Repeat for each metadata column to evaluate as a slice.")
    parser.add_argument("--metadata", action="append", default=None)
    parser.add_argument("--baseline-column", default=None)
    parser.add_argument("--protocol", default=None)
    parser.add_argument("--sampling-design", default=None, help="Local sampling-design/v1 YAML with declared independent units.")
    parser.add_argument("--evaluation-design", default=None, help="Local evaluation-design/v1 YAML for split auditing and eligibility.")
    parser.add_argument("--training-reference", default=None, help="Local declared training/reference table; never uploaded.")
    parser.add_argument("--reference-complete", action="store_true", help="Declare that the supplied reference covers the model's original training records.")
    parser.add_argument("--design-failure-mode", choices=["stop", "local_only"], default="stop")
    parser.add_argument("--primary-metric", default=None, help="Default: RMSE / AUROC / macro AUROC, or the protocol primary metric.")
    parser.add_argument("--resamples", type=int, default=None)
    parser.add_argument("--confidence-level", type=float, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--min-samples", type=int, default=None)
    parser.add_argument("--min-slice-size", type=int, default=None)
    parser.add_argument("--no-uncertainty", action="store_true")
    parser.add_argument("--include-slice-uncertainty", action="store_true", default=None)
    parser.add_argument("--quality-policy", default=None)
    parser.add_argument("--release-policy", default=None)
    parser.add_argument("--output-dir", default="reports/evaluation")
    parser.add_argument("--reference", default=None, help="Reference prediction table for cohort degradation diagnostics.")
    parser.add_argument("--independent-cohorts", action="store_true", help="Declare independent observations within/between reference and current cohorts for unpaired delta intervals.")
    parser.add_argument("--degradation-threshold", type=float, default=None, help="Practical degradation threshold in primary-metric units.")
    parser.add_argument("--prevalence-threshold", type=float, default=0.1)
    parser.add_argument("--numeric-metadata", action="append", default=None)
    parser.add_argument("--categorical-metadata", action="append", default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="privatelabbench", description="Local-first evaluation for scientific machine learning on private data.")
    sub = parser.add_subparsers(dest="command", required=True)

    evaluate = sub.add_parser("evaluate", help="Evaluate a prediction CSV and write a verifiable local receipt.")
    add_simple_prediction_args(evaluate)
    init = sub.add_parser("init", help="Generate a reproducible local evaluation config without copying dataset rows.")
    add_simple_prediction_args(init)
    init.add_argument("--out", default="evaluation.yaml")
    init.add_argument("--force", action="store_true", help="Overwrite an existing config.")

    audit_design = sub.add_parser("audit-design", help="Audit declared split integrity locally without scoring or publishing rows.")
    audit_design.add_argument("--evaluation", required=True)
    audit_design.add_argument("--training-reference", default=None)
    audit_design.add_argument("--reference-complete", action="store_true")
    audit_design.add_argument("--protocol", required=True, help="Local evaluation-design/v1 YAML, or an evaluation protocol containing evaluation_design.")
    audit_design.add_argument("--out", default="reports/design_audit.json")

    tdc_prepare = sub.add_parser("tdc-prepare", help="Verify an official TDC cache and create a fixed-test prediction template.")
    tdc_prepare.add_argument("--dataset", required=True)
    tdc_prepare.add_argument("--cache-dir", default="outputs/tdc")
    tdc_prepare.add_argument("--download", action="store_true", help="Explicitly fetch the public ADMET benchmark group through the optional TDC loader.")
    tdc_prepare.add_argument("--out", required=True)
    tdc_evaluate = sub.add_parser("tdc-evaluate", help="Evaluate external predictions on a pinned official TDC test set.")
    tdc_evaluate.add_argument("predictions")
    tdc_evaluate.add_argument("--dataset", required=True)
    tdc_evaluate.add_argument("--cache-dir", default="outputs/tdc")
    tdc_evaluate.add_argument("--prediction-column", default="prediction")
    tdc_evaluate.add_argument("--upstream-test-order", action="store_true", help="Explicitly declare upstream test-row order when predictions have no generated IDs.")
    tdc_evaluate.add_argument("--release-policy", default=None)
    tdc_evaluate.add_argument("--output-dir", default="reports/tdc")

    run = sub.add_parser("run", help="Run a local evaluation task from a YAML config file.")
    run.add_argument("config_path", help="Path to a PrivateLabBench YAML config.")
    run.add_argument("--protocol", default=None, help="Exact plb://namespace/name@version or local protocol YAML.")

    sub.add_parser("list-protocols", help="List bundled and installed versioned evaluation protocols.")
    show_protocol = sub.add_parser("show-protocol", help="Show frozen protocol rules and their SHA-256 digest.")
    show_protocol.add_argument("protocol", help="Exact plb:// reference or local YAML path.")

    aggregate = sub.add_parser("aggregate", help="Verify and summarize compatible shareable receipts across sites.")
    aggregate.add_argument("inputs", nargs="+")
    aggregate.add_argument("--site", action="append", default=None, help="One public-safe label per input, in input order; defaults to site-1, site-2, ...")
    aggregate.add_argument("--model", action="append", default=None, help="model-id@revision: once for all evaluation receipts, once per receipt, or A then B for paired receipts.")
    aggregate.add_argument("--metric", default=None, help="Defaults to the protocol primary metric.")
    aggregate.add_argument("--assume-disjoint-sites", action="store_true", help="Declare disjoint observations with identical scoring/weighting semantics; required for point pooling.")
    aggregate.add_argument("--range-threshold", type=float, default=None, help="Practical threshold for the descriptive best-to-worst site gap.")
    aggregate.add_argument("--signing-secret", default=None)
    aggregate.add_argument("--trust-store", default=None)
    aggregate.add_argument("--require-trusted-signer", action="store_true")
    aggregate.add_argument("--require-external-validation", action="store_true", help="Require approved validation profiles and matching declared model identities in every input.")
    aggregate.add_argument("--release-policy", default=None, help="Reviewed export policy approving public site/model labels.")
    aggregate.add_argument("--out", default="reports/cross_site_aggregate.json", help="Local aggregate artifact; optional public sibling uses .shareable.json.")

    validate = sub.add_parser("validate-config", help="Validate a YAML config before running it.")
    validate.add_argument("config_path", help="Path to a PrivateLabBench YAML config.")

    gate = sub.add_parser("gate", help="Evaluate a versioned model-quality policy against an existing artifact.")
    gate.add_argument("artifact")
    gate.add_argument("--policy", required=True, help="Standalone quality-policy/v1 YAML.")
    gate.add_argument("--out", default=None, help="Optional local decision artifact; preserves the source.")
    gate.add_argument("--signing-secret", default=None)
    gate.add_argument("--trust-store", default=None)
    gate.add_argument("--require-trusted-signer", action="store_true")

    sub.add_parser("list-tasks", help="List built-in and installed third-party evaluation tasks.")
    sub.add_parser("list-privacy-attacks", help="List registered empirical privacy-audit attacks.")
    sub.add_parser("list-packs", help="List bundled/source community benchmark packs.")

    run_pack = sub.add_parser("run-pack", help="Run a versioned community benchmark pack.")
    run_pack.add_argument("pack", help="Pack ID or explicit id@version reference.")

    compare = sub.add_parser(
        "compare",
        help="Compare configs (legacy mode) or two prediction tables on exactly matched samples.",
    )
    compare.add_argument(
        "inputs",
        nargs="+",
        help="Config files for legacy comparison, or exactly two prediction CSVs when --target is supplied.",
    )
    compare.add_argument("--target", default=None, help="Enable paired prediction-table mode and specify the target column.")
    prediction_group = compare.add_mutually_exclusive_group()
    prediction_group.add_argument("--prediction-column", default=None, help="Shared prediction/probability column in both tables. Default in paired mode: prediction")
    prediction_group.add_argument("--prediction-columns", nargs="+", default=None, help="Shared ordered multiclass probability columns in both tables.")
    compare.add_argument("--task-type", choices=["regression", "classification", "multiclass"], default=None)
    compare.add_argument("--class-labels", nargs="+", default=None, help="Ordered labels for binary/multiclass comparison.")
    compare.add_argument("--sample-id-column", default="sample_id", help="Stable ID used for exact paired alignment.")
    compare.add_argument("--metric", default=None, help="Metric to compare. Defaults: rmse, auroc, macro_auroc_ovr by task type.")
    compare.add_argument("--model-a-name", default=None)
    compare.add_argument("--model-b-name", default=None)
    compare.add_argument("--protocol", default=None, help="Bind an exact versioned protocol and its comparison rules.")
    compare.add_argument("--sampling-design", default=None, help="Declared cluster/hierarchical sampling and optional slice test-family policy.")
    compare.add_argument("--evaluation-design", default=None)
    compare.add_argument("--training-reference", default=None, help="Common declared training/reference records for both compared models.")
    compare.add_argument("--reference-complete", action="store_true")
    compare.add_argument("--design-failure-mode", choices=["stop", "local_only"], default="stop")
    compare.add_argument("--confidence-level", type=float, default=None, help="Default: 0.95, or protocol setting.")
    compare.add_argument("--resamples", type=int, default=None, help="Paired bootstrap resamples. Default: 1000, or protocol setting.")
    compare.add_argument("--permutations", type=int, default=None, help="Prediction-swap permutations; 0 disables. Default: 1000, or protocol setting.")
    compare.add_argument("--seed", type=int, default=None, help="Default: 13, or protocol setting.")
    compare.add_argument("--min-samples", type=int, default=None, help="Default: 20, or protocol setting.")
    compare.add_argument("--practical-threshold", type=float, default=None, help="Required direction-adjusted improvement. Default: 0, or protocol setting.")
    compare.add_argument("--noninferiority-margin", type=float, default=None, help="Optional noninferiority margin for Model A, expressed in selected-metric units after direction adjustment.")
    compare.add_argument("--slice-columns", nargs="*", default=None, help="Metadata columns for paired slice comparison.")
    compare.add_argument("--min-slice-size", type=int, default=None, help="Default: 5, or protocol setting.")
    compare.add_argument("--include-slice-uncertainty", action="store_true", default=None, help="Also run paired bootstrap intervals inside eligible slices.")
    compare.add_argument("--signing-secret", default=None, help="Optional HMAC secret for local/shareable paired-comparison artifacts.")
    compare.add_argument("--release-policy", default=None, help="Explicit release-policy/v1 YAML; without it the comparison stays local.")
    compare.add_argument("--report", default="reports/model_comparison.md")
    compare.add_argument("--json-report", default="reports/model_comparison.json")

    verify_any = sub.add_parser("verify", help="Verify a receipt, run manifest, or JSON report.")
    verify_any.add_argument("artifact", help="Path to a receipt, run manifest, or JSON report.")
    verify_any.add_argument("--signing-secret", default=None, help="Optional HMAC signing secret.")
    verify_any.add_argument("--trust-store", default=None, help="Offline receipt-trust-store/v1 with pinned Ed25519 public keys.")
    verify_any.add_argument("--require-trusted-signer", action="store_true", help="Fail unless a non-revoked pinned signer authenticates the receipt.")
    verify_any.add_argument("--expected-protocol-sha256", default=None, help="Require the signature to bind this independently known public protocol digest.")
    verify_any.add_argument("--json", action="store_true", help="Print independently named verification outcomes as JSON.")

    sign = sub.add_parser("sign", help="Apply disclosure policy and sign an aggregate receipt with a local Ed25519 key.")
    sign.add_argument("artifact", help="Local evaluation receipt or paired-comparison artifact.")
    sign.add_argument("--policy", required=True)
    sign.add_argument("--private-key", required=True, help="Local unencrypted Ed25519 PEM; never included in output.")
    sign.add_argument("--signer-id", required=True)
    sign.add_argument("--key-id", required=True)
    sign.add_argument("--out", required=True)
    sign.add_argument("--signing-secret", default=None, help="Shared secret if the local source artifact uses HMAC.")
    sign.add_argument("--protocol-id", default=None)
    sign.add_argument("--protocol-version", default=None)
    sign.add_argument("--protocol-sha256", default=None)
    sign.add_argument("--model-id", default=None)
    sign.add_argument("--model-revision", default=None)

    release_check = sub.add_parser("release-check", help="Dry-run disclosure checks without exporting or uploading anything.")
    release_check.add_argument("artifact", help="Local evaluation receipt or paired-comparison artifact.")
    release_check.add_argument("--policy", required=True, help="release-policy/v1 YAML file.")

    verify_report_parser = sub.add_parser("verify-report", help="Verify JSON report integrity and optional HMAC signature.")
    verify_report_parser.add_argument("json_report", help="Path to a PrivateLabBench JSON report.")
    verify_report_parser.add_argument("--signing-secret", default=None, help="Optional HMAC signing secret.")

    verify_manifest = sub.add_parser("verify-manifest", help="Verify a run manifest and its bound artifacts.")
    verify_manifest.add_argument("manifest", help="Path to a PrivateLabBench run manifest.")
    verify_manifest.add_argument("--signing-secret", default=None, help="Optional HMAC signing secret.")

    eval_mol = sub.add_parser("eval-molecules", help="Evaluate a molecular property prediction CSV locally.")
    eval_mol.add_argument("csv_path", help="Path to a CSV containing SMILES and target columns.")
    add_common_eval_args(eval_mol)
    eval_mol.add_argument("--report", default="reports/molecule_eval_report.md")

    eval_fed = sub.add_parser("eval-federated", help="Evaluate multiple local lab CSVs and aggregate metrics.")
    eval_fed.add_argument("client_dir", help="Directory containing one CSV per lab/site.")
    add_common_eval_args(eval_fed)
    eval_fed.add_argument("--report", default="reports/federated_eval_report.md")

    eval_pred = sub.add_parser("eval-predictions", help="Evaluate a local prediction table.")
    eval_pred.add_argument("csv_path", help="Path to a CSV prediction table.")
    eval_pred.add_argument("--target", required=True, help="Target column name.")
    prediction_group = eval_pred.add_mutually_exclusive_group(required=True)
    prediction_group.add_argument("--prediction-column", help="Single prediction/probability column for regression or binary classification.")
    prediction_group.add_argument("--prediction-columns", nargs="+", help="Ordered probability columns for multiclass classification.")
    eval_pred.add_argument("--task-type", choices=["regression", "classification", "multiclass"], default=None, help="Problem type. Multiclass is inferred when --prediction-columns has multiple columns.")
    eval_pred.add_argument("--class-labels", nargs="+", default=None, help="Ordered class labels matching --prediction-columns.")
    eval_pred.add_argument("--sample-id-column", default="sample_id", help="Stable sample identifier column.")
    eval_pred.add_argument("--require-sample-id", action="store_true", help="Fail if the sample ID column is missing.")
    eval_pred.add_argument("--metadata-columns", nargs="*", default=None, help="Metadata columns that must be present.")
    eval_pred.add_argument("--slice-columns", nargs="*", default=None, help="Metadata columns to aggregate metrics by.")
    eval_pred.add_argument("--min-slice-size", type=int, default=2, help="Do not report metrics for slices smaller than this count.")
    eval_pred.add_argument("--split-column", default=None, help="Optional train/test split column for membership-risk scoring.")
    add_privacy_args(eval_pred)
    eval_pred.add_argument("--report", default="reports/prediction_eval_report.md")
    eval_pred.add_argument("--json-report", default="reports/prediction_eval_report.json")
    return parser


def make_privacy_config(args: argparse.Namespace) -> PrivacyConfig:
    return PrivacyConfig(mode=args.privacy, epsilon=args.epsilon, sensitivity=args.sensitivity, seed=args.seed)


def _print_receipt_paths(summary: dict[str, object]) -> None:
    manifest = Path(str(summary["manifest"]))
    base = manifest.stem[: -len("_manifest")] if manifest.stem.endswith("_manifest") else manifest.stem
    receipt = manifest.with_name(f"{base}_receipt.json")
    shareable = manifest.with_name(f"{base}_receipt.shareable.json")
    markdown = manifest.with_name(f"{base}_receipt.md")
    if receipt.exists():
        print(f"Local receipt saved to: {receipt}")
        if shareable.exists():
            print(f"Shareable receipt saved to: {shareable}")
        else:
            print(f"Export blocked; see: {shareable.with_suffix('.release-audit.json')}")
        print(f"Receipt Markdown saved to: {markdown}")


def run_from_config(args: argparse.Namespace) -> int:
    from privatelabbench.design_audit import DesignAuditFailure
    try:
        summary = run_config(args.config_path, protocol_override=args.protocol)
    except DesignAuditFailure as exc:
        print(str(exc))
        return 1
    print_run_summary(summary)
    _print_receipt_paths(summary)
    if any(summary.get(key, {}).get("status") == "fail" for key in ("design_audit", "reference_design_audit")):
        return 1
    return QUALITY_EXIT_CODES[summary["quality_gate"]["status"]] if "quality_gate" in summary else 0


def gate_command(args: argparse.Namespace) -> int:
    try:
        source = Path(args.artifact)
        if args.out and source.resolve() == Path(args.out).resolve():
            raise ValueError("Choose a different output path to preserve evaluation evidence")
        if args.out:
            Path(args.out).unlink(missing_ok=True)
        trust = _read_release_policy(args.trust_store) if args.trust_store else None
        verification = verify_report(str(source), signing_secret=_secret(args), trust_store=trust, require_trusted_signer=args.require_trusted_signer)
        if not verification.get("valid"):
            raise ValueError(f"Artifact verification failed: {verification.get('reason')}")
        artifact = json.loads(source.read_text(encoding="utf-8"))
        policy = yaml.safe_load(Path(args.policy).read_text(encoding="utf-8"))
        result = evaluate_quality_gate(artifact, policy)
        result["source_evidence_level"] = verification.get("evidence_level", "integrity_only")
        if args.out:
            from privatelabbench.reports.integrity import attach_integrity_metadata
            from privatelabbench.privacy.export import atomic_write_json
            atomic_write_json(Path(args.out), attach_integrity_metadata(result))
        print(json.dumps(result, indent=2, allow_nan=False))
        return QUALITY_EXIT_CODES[result["status"]]
    except (OSError, ValueError, TypeError, AttributeError, yaml.YAMLError) as exc:
        print(json.dumps({"schema_version": "quality-gate/v1", "scope": "local", "status": "investigate", "reason": str(exc)}))
        return 2


def simple_evaluation_command(args: argparse.Namespace) -> int:
    from privatelabbench.evaluate import evaluation_summary, make_evaluation_config
    output = Path(args.output_dir).resolve()
    config_path = Path(args.out).resolve() if args.command == "init" else output / "evaluation.yaml"
    public = output / "evaluation_receipt.shareable.json"
    public_markdown = output / "evaluation_receipt.md"
    generated_header = "# Generated by plb evaluate/init. Contains local paths and settings; no dataset rows.\n"
    source = Path(args.predictions).resolve()
    protected = (config_path, output / "evaluation.json", output / "evaluation.md", output / "evaluation_manifest.json", output / "evaluation_receipt.json", public, public_markdown, public.with_suffix(".release-audit.json"), output / "audit.jsonl", output / ".plb-release-ledger.json", output / ".plb-release.lock")
    inputs = {source}
    for key in ("training_reference", "reference", "evaluation_design", "sampling_design", "quality_policy", "release_policy"):
        if getattr(args, key, None): inputs.add(Path(getattr(args, key)).resolve())
    if args.protocol and not args.protocol.startswith("plb://"): inputs.add(Path(args.protocol).resolve())
    if any(path in inputs for path in protected):
        print("Evaluation rejected: output paths must be separate from all input tables and policy/protocol files")
        return 2
    if args.command == "evaluate":
        public.unlink(missing_ok=True)
        public_markdown.unlink(missing_ok=True)
    try:
        if config_path.exists() and (args.command == "init" and not args.force or args.command == "evaluate" and not config_path.read_text(encoding="utf-8").startswith(generated_header)):
            raise ValueError("Config already exists; choose another --out/--output-dir, or use init --force to overwrite deliberately")
        uncertainty = {key: value for key, value in {"resamples": args.resamples, "confidence_level": args.confidence_level, "seed": args.seed, "min_samples": args.min_samples, "include_slices": args.include_slice_uncertainty}.items() if value is not None}
        if args.no_uncertainty:
            uncertainty["enabled"] = False
        config = make_evaluation_config(source, output_dir=output, protocol=args.protocol, primary_metric=args.primary_metric, uncertainty=uncertainty, min_slice_size=args.min_slice_size, quality_policy=_read_release_policy(args.quality_policy) if args.quality_policy else None, release_policy=_read_release_policy(args.release_policy) if args.release_policy else None, sampling_design=_read_release_policy(args.sampling_design) if args.sampling_design else None, evaluation_design=_read_release_policy(args.evaluation_design) if args.evaluation_design else None, target=args.target, prediction_column=args.prediction_column, prediction_columns=args.prediction_columns, sample_id_column=args.sample_id_column, task_type=args.task_type, class_labels=args.class_labels, slices=args.slice, metadata=args.metadata, baseline_column=args.baseline_column)
        if args.reference_complete and not args.training_reference:
            raise ValueError("--reference-complete requires --training-reference")
        if config.get("evaluation_design"):
            config["design_audit"] = {"training_reference": str(Path(args.training_reference).resolve()) if args.training_reference else None, "reference_complete": args.reference_complete, "failure_mode": args.design_failure_mode}
        elif args.training_reference or args.reference_complete or args.design_failure_mode != "stop":
            raise ValueError("Training-reference audit options require an evaluation design")
        if args.reference:
            config["diagnostics"] = {"reference_path": str(Path(args.reference).resolve()), "independent_cohorts": args.independent_cohorts, "prevalence_threshold": args.prevalence_threshold, "numeric_metadata": args.numeric_metadata or [], "categorical_metadata": args.categorical_metadata or [], "practical_thresholds": {config["evaluation"]["primary_metric"]: args.degradation_threshold} if args.degradation_threshold is not None else {}}
        elif args.independent_cohorts or args.degradation_threshold is not None or args.numeric_metadata or args.categorical_metadata:
            raise ValueError("Cohort diagnostic options require --reference REFERENCE.csv")
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(generated_header + yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        if args.command == "init":
            print(f"Config saved: {config_path}\nRun: plb run \"{config_path}\"")
            return 0
        summary = run_config(str(config_path))
        report = json.loads(Path(summary["json_report"]).read_text(encoding="utf-8"))
        release = json.loads(public.with_suffix(".release-audit.json").read_text(encoding="utf-8"))
        receipt = public if public.exists() else output / "evaluation_receipt.json"
        print(evaluation_summary(summary, report, config["evaluation"]["primary_metric"], release, receipt))
        if any(summary.get(key, {}).get("status") == "fail" for key in ("design_audit", "reference_design_audit")):
            return 1
        return QUALITY_EXIT_CODES[summary["quality_gate"]["status"]] if "quality_gate" in summary else 0
    except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError) as exc:
        if args.command == "evaluate":
            public.unlink(missing_ok=True)
            public_markdown.unlink(missing_ok=True)
        print(f"Evaluation rejected: {exc}")
        from privatelabbench.design_audit import DesignAuditFailure
        return 1 if isinstance(exc, DesignAuditFailure) else 2


def tdc_command(args: argparse.Namespace) -> int:
    from privatelabbench.integrations.tdc import prepare_template, evaluate_tdc
    try:
        if args.command == "tdc-prepare":
            result = prepare_template(args.cache_dir, args.dataset, args.out, download=args.download)
            print(f"TDC {result['dataset']}: {result['n_test']} fixed test records; metric {result['metric']}")
            print(f"Prediction template: {result['template']}\nProtocol: {result['protocol']}")
        else:
            summary = evaluate_tdc(args.cache_dir, args.dataset, args.predictions, args.output_dir, prediction_column=args.prediction_column, upstream_test_order=args.upstream_test_order, release_policy_path=args.release_policy)
            print_run_summary(summary)
            print(f"Official TDC primary metric: {summary['tdc']['metric']}")
            _print_receipt_paths(summary)
        return 0
    except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError) as exc:
        print(f"TDC workflow rejected: {exc}")
        return 2


def audit_design_command(args: argparse.Namespace) -> int:
    from privatelabbench.design_audit import EvaluationDesign, prepare_evaluation
    from privatelabbench.privacy.export import atomic_write_json
    from privatelabbench.reports.integrity import attach_integrity_metadata
    output = Path(args.out)
    protected = {Path(args.evaluation).resolve(), *([Path(args.training_reference).resolve()] if args.training_reference else [])}
    if not args.protocol.startswith("plb://"):
        protected.add(Path(args.protocol).resolve())
    if output.resolve() in protected:
        print("Audit rejected: choose a separate output path")
        return 2
    try:
        output.unlink(missing_ok=True)
        protocol = None
        if args.protocol.startswith("plb://"):
            from privatelabbench.protocols import resolve_protocol
            protocol = resolve_protocol(args.protocol)
            value = protocol.as_dict().get("evaluation_design")
        else:
            value = _read_release_policy(args.protocol)
            if isinstance(value, dict) and value.get("schema_version") == "evaluation-protocol/v1":
                from privatelabbench.protocols import EvaluationProtocol
                protocol = EvaluationProtocol.from_dict(value)
                value = protocol.as_dict().get("evaluation_design")
        if value is None:
            raise ValueError("The selected protocol does not declare evaluation_design")
        prepared = prepare_evaluation(args.evaluation, EvaluationDesign.from_dict(value), training_reference=args.training_reference, reference_complete=args.reference_complete)
        artifact = prepared.artifact
        if protocol:
            artifact["local"]["protocol"] = protocol.identity()
            artifact = attach_integrity_metadata(artifact)
        atomic_write_json(output, artifact)
        summary = artifact["audit"]
        print(f"Evaluation design: {summary['status']} (provided records only)")
        print(f"Training reference present: {summary['training_reference_present']}; declared complete: {summary['reference_declared_complete']}")
        for name, finding in summary["findings"].items():
            print(f"  {name}: {finding['status']}; affected records: {finding['affected_records']}")
        print(f"Local audit: {output}")
        return 0 if summary["status"] == "pass" else 1 if summary["status"] == "fail" else 2
    except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError) as exc:
        print(f"Audit rejected: {exc}")
        return 2


def aggregate_command(args: argparse.Namespace) -> int:
    from privatelabbench.aggregate import aggregate_receipts, render_aggregate
    from privatelabbench.privacy.export import atomic_write_json
    output = Path(args.out)
    public = output.with_name(f"{output.stem}.shareable{output.suffix}")
    markdown = output.with_suffix(".md")
    protected = {Path(path).resolve() for path in args.inputs}
    related = (output, public, markdown, public.with_suffix(".release-audit.json"), output.parent / ".plb-release-ledger.json", output.parent / ".plb-release.lock")
    if any(path.resolve() in protected for path in related):
        raise ValueError("Choose aggregate output paths separate from every input receipt")
    public.unlink(missing_ok=True)
    markdown.unlink(missing_ok=True)
    try:
        models = []
        for reference in args.model or ():
            if "@" not in reference:
                raise ValueError("--model requires an explicit model-id@revision")
            model_id, revision = reference.rsplit("@", 1)
            models.append({"id": model_id, "revision": revision})
        artifact = aggregate_receipts(args.inputs, sites=args.site, models=models, metric=args.metric, assume_disjoint_sites=args.assume_disjoint_sites, range_threshold=args.range_threshold, signing_secret=_secret(args), trust_store=_read_release_policy(args.trust_store) if args.trust_store else None, require_trusted_signer=args.require_trusted_signer, require_external_validation=args.require_external_validation)
        atomic_write_json(output, artifact)
        decision = publish_shareable_artifact(artifact, _read_release_policy(args.release_policy) if args.release_policy else None, public, signing_secret=_secret(args))
        if decision.decision == "allow":
            approved = json.loads(public.read_text(encoding="utf-8"))
            markdown.write_text(render_aggregate(approved), encoding="utf-8")
        shared = artifact["shareable"]
        print(f"PrivateLabBench cross-site evaluation: {shared['metric']}")
        for model in shared["models"]:
            print(f"Model {model['model']['id']}@{model['model']['revision']}")
            for row in model["sites"]:
                print(f"  {row['site']}: N={row['n_samples']}, estimate={row['estimate']:.6g}")
            print(f"  Site range: {model['summary']['range']['absolute']:.6g}; pooling: {model['summary']['pooled']['status']}")
        print(f"Local aggregate: {output}")
        print(f"Release: {decision.decision}; {public if decision.decision == 'allow' else public.with_suffix('.release-audit.json')}")
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        public.unlink(missing_ok=True)
        markdown.unlink(missing_ok=True)
        print(f"Aggregation rejected: {exc}")
        return 2


def print_validation_result(result: ConfigValidationResult) -> None:
    print("PrivateLabBench config validation")
    print(f"Config: {result.config_path}")
    if result.project:
        print(f"Project: {result.project}")
    if result.workflow:
        print(f"Task: {result.workflow}")
    print(f"Valid: {result.valid}")
    for warning in result.warnings:
        print(f"Warning: {warning}")
    for error in result.errors:
        print(f"Error: {error}")


def validate_config_command(args: argparse.Namespace) -> int:
    result = validate_config(args.config_path)
    print_validation_result(result)
    return 0 if result.valid else 1


def list_tasks_command() -> int:
    ensure_builtin_tasks_registered()
    discover_entrypoint_tasks()
    print("PrivateLabBench tasks")
    for spec in list_tasks():
        description = f" — {spec.description}" if spec.description else ""
        print(f"{spec.id}{description}")
    return 0


def list_privacy_attacks_command() -> int:
    ensure_builtin_privacy_attacks_registered()
    print("PrivateLabBench privacy attacks")
    for spec in list_privacy_attacks():
        baseline = " [baseline]" if spec.baseline else ""
        description = f" — {spec.description}" if spec.description else ""
        print(f"{spec.id}{baseline} — {spec.evidence_level}{description}")
    return 0


def list_packs_command() -> int:
    print("PrivateLabBench benchmark packs")
    for pack in discover_benchmark_packs():
        print(f"{pack.ref} — {pack.domain} — {pack.description}")
    return 0


def run_pack_command(args: argparse.Namespace) -> int:
    summary = run_benchmark_pack(args.pack)
    print_run_summary(summary)
    print(f"Benchmark pack: {summary['benchmark_pack']}")
    _print_receipt_paths(summary)
    return QUALITY_EXIT_CODES[summary["quality_gate"]["status"]] if "quality_gate" in summary else 0


def compare_command(args: argparse.Namespace) -> int:
    if args.target is None and len(args.inputs) == 2 and all(Path(path).suffix.lower() == ".csv" for path in args.inputs):
        from privatelabbench.evaluate import prediction_bindings
        from privatelabbench.protocols import resolve_protocol
        rules = resolve_protocol(args.protocol).as_dict() if args.protocol else None
        audit_value = _read_release_policy(args.evaluation_design) if args.evaluation_design else rules.get("evaluation_design") if rules else None
        selected_frame = None
        if audit_value is not None:
            from privatelabbench.design_audit import EvaluationDesign, select_eligible
            selected_frame = select_eligible(args.inputs[0], EvaluationDesign.from_dict(audit_value))
        bound = prediction_bindings(args.inputs[0], prediction_column=args.prediction_column, prediction_columns=args.prediction_columns, sample_id_column=args.sample_id_column, task_type=args.task_type or (rules["task_type"] if rules else None), class_labels=args.class_labels or (rules["input_schema"]["class_labels"] if rules else None), slices=args.slice_columns, frame=selected_frame)
        args.target = bound["target_column"]
        args.task_type = bound["task_type"]
        args.class_labels = bound["class_labels"]
    if args.target is None:
        if args.protocol:
            raise ValueError("--protocol requires paired CSV mode with --target")
        if args.evaluation_design or args.training_reference or args.reference_complete:
            raise ValueError("Evaluation-design comparison requires paired CSV inputs")
        result = compare_configs(args.inputs, markdown_path=args.report, json_path=args.json_report)
        print("PrivateLabBench config comparison")
        print(f"Runs: {result['n_runs']}")
        print(f"Markdown report saved to: {Path(result['markdown_report'])}")
        print(f"JSON report saved to: {Path(result['json_report'])}")
        return 0

    if len(args.inputs) != 2:
        raise ValueError("Paired prediction-table comparison requires exactly two CSV inputs")
    prediction_column = args.prediction_column
    if prediction_column is None and not args.prediction_columns:
        prediction_column = "prediction"
    result = compare_prediction_files(
        args.inputs[0],
        args.inputs[1],
        target=args.target,
        prediction_column=prediction_column,
        prediction_columns=args.prediction_columns,
        sample_id_column=args.sample_id_column,
        task_type=args.task_type,
        class_labels=args.class_labels,
        slice_columns=args.slice_columns,
        model_a_name=args.model_a_name,
        model_b_name=args.model_b_name,
        metric=args.metric,
        confidence_level=args.confidence_level,
        resamples=args.resamples,
        permutations=args.permutations,
        seed=args.seed,
        min_samples=args.min_samples,
        practical_threshold=args.practical_threshold,
        noninferiority_margin=args.noninferiority_margin,
        include_slice_uncertainty=args.include_slice_uncertainty,
        min_slice_size=args.min_slice_size,
        markdown_path=args.report,
        json_path=args.json_report,
        signing_secret=args.signing_secret or os.getenv("PRIVATELABBENCH_SIGNING_SECRET"),
        release_policy=_read_release_policy(args.release_policy) if args.release_policy else None,
        protocol=args.protocol,
        sampling_design=_read_release_policy(args.sampling_design) if args.sampling_design else None,
        evaluation_design=_read_release_policy(args.evaluation_design) if args.evaluation_design else None,
        design_audit_options={"training_reference": args.training_reference, "reference_complete": args.reference_complete, "failure_mode": args.design_failure_mode},
    )
    interval = result["paired_interval"]
    print("PrivateLabBench paired prediction comparison")
    print(f"Samples: {result['n_samples']}")
    if "n_independent_units" in interval:
        print(f"Independent units: {interval['n_independent_units']}; method: {interval['method']}")
    print(f"Metric: {result['metric']} ({result['direction']})")
    print(f"Model A: {result['model_a']['name']} = {float(result['model_a']['selected_metric']):.6f}")
    print(f"Model B: {result['model_b']['name']} = {float(result['model_b']['selected_metric']):.6f}")
    print(f"Improvement A over B: {float(result['improvement_a_over_b']):.6f}")
    if interval.get("lower") is not None and interval.get("upper") is not None:
        print(
            f"{float(interval['confidence_level']):.0%} paired CI: "
            f"[{float(interval['lower']):.6f}, {float(interval['upper']):.6f}]"
        )
    randomization = result["randomization_test"]
    if randomization.get("p_value") is not None:
        print(f"Paired randomization p-value: {float(randomization['p_value']):.6g}")
    print(f"Decision: {result['decision']['confidence_interval']}")
    if result.get("multiplicity"):
        family = result["multiplicity"]
        print(f"Slice tests: {family['family']} ({family['method']}), {family['n_usable_tests']}/{family['n_tests']} usable; {family['status']}")
    print(f"Markdown report saved to: {Path(result['markdown_report'])}")
    print(f"Local JSON artifact saved to: {Path(result['json_report'])}")
    if result["shareable_json_report"]:
        print(f"Shareable JSON artifact saved to: {Path(result['shareable_json_report'])}")
    else:
        print("Export blocked; inspect the local release audit or supply --release-policy.")
    if any(audit.get("status") == "fail" for audit in result.get("design_audits", [])):
        return 1
    return 0


def _secret(args: argparse.Namespace) -> str | None:
    return args.signing_secret or os.getenv("PRIVATELABBENCH_SIGNING_SECRET")


def _read_release_policy(path: str) -> object:
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {"schema_version": "invalid"}


def release_check_command(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
        policy = _read_release_policy(args.policy)
        evidence = None
        if isinstance(payload, dict) and payload.get("scope") == "local":
            # The complete local evidence is bound into the local receipt.
            evidence = payload.get("local", {}).get("release_evidence")
        decision, _ = check_release(payload, policy, evidence=evidence)
        print(json.dumps(decision.as_dict(), indent=2))
        print("Dry run only; repeated-release history is checked during export.")
        return 0 if decision.decision == "allow" else 1
    except (OSError, ValueError, TypeError):
        print(json.dumps({"decision": "needs_review", "reason_codes": ["unreadable_policy_or_artifact"]}))
        return 1


def _print_basic_verification(result: dict[str, object]) -> int:
    print(f"Artifact: {result.get('path')}")
    print(f"Hash valid: {result.get('hash_valid', result.get('valid'))}")
    print(f"Reason: {result.get('reason')}")
    if result.get("schema_version"):
        print(f"Schema: {result.get('schema_version')}")
    if result.get("scope"):
        print(f"Scope: {result.get('scope')}")
    if result.get("payload_sha256"):
        print(f"Payload SHA256: {result.get('payload_sha256')}")
    if "evidence_level" in result:
        print(f"Signature present: {result.get('signature_present')}")
        print(f"Signature valid: {result.get('signature_valid')}")
        print(f"Signer trusted: {result.get('signer_trusted')}")
        print(f"Signer check: {result.get('trust_reason')}")
        print(f"Protocol bound: {result.get('protocol_bound')}")
        print(f"Evidence level: {result.get('evidence_level')}")
        print("Execution and scientific validity are not independently established.")
    return 0 if result.get("valid") else 1


def verify_any_command(args: argparse.Namespace) -> int:
    path = Path(args.artifact)
    payload = json.loads(path.read_text(encoding="utf-8"))
    schema = payload.get("schema_version") if isinstance(payload, dict) else None
    trust_path = getattr(args, "trust_store", None)
    try:
        trust = yaml.safe_load(Path(trust_path).read_text(encoding="utf-8")) if trust_path else None
    except (OSError, yaml.YAMLError):
        trust = {"schema_version": "invalid"}
    options = {"signing_secret": _secret(args), "trust_store": trust, "require_trusted_signer": getattr(args, "require_trusted_signer", False), "expected_protocol_sha256": getattr(args, "expected_protocol_sha256", None)}
    if schema == RECEIPT_SCHEMA_VERSION:
        result = verify_receipt(path, **options)
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2))
            return 0 if result.get("valid") else 1
        return _print_basic_verification(result)
    if schema == "run-manifest/v0.1":
        result = verify_run_manifest(path, signing_secret=_secret(args))
        result["schema_version"] = schema
        if options["require_trusted_signer"] or options["expected_protocol_sha256"]:
            result.update(valid=False, reason="public_signer_verification_requires_receipt")
        if getattr(args, "json", False):
            print(json.dumps(result, indent=2))
            return 0 if result.get("valid") else 1
        return _print_basic_verification(result)
    result = verify_report(str(path), **options)
    result["schema_version"] = schema
    result["scope"] = payload.get("scope") if isinstance(payload, dict) else None
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return 0 if result.get("valid") else 1
    return _print_basic_verification(result)


def sign_command(args: argparse.Namespace) -> int:
    source = Path(args.artifact)
    if source.resolve() == Path(args.out).resolve():
        raise ValueError("Choose a separate signed output path; the local source must be preserved")
    Path(args.out).unlink(missing_ok=True)
    check = verify_report(str(source), signing_secret=_secret(args))
    if not check.get("valid"):
        raise ValueError("Source artifact failed its integrity check")
    payload = json.loads(source.read_text(encoding="utf-8"))
    signer = {"private_key": args.private_key, "signer_id": args.signer_id, "key_id": args.key_id}
    protocol = (args.protocol_id, args.protocol_version, args.protocol_sha256)
    if any(protocol):
        if not all(protocol):
            raise ValueError("Protocol binding needs --protocol-id, --protocol-version, and --protocol-sha256")
        signer["protocol"] = {"id": args.protocol_id, "version": args.protocol_version, "sha256": args.protocol_sha256}
    if args.model_id or args.model_revision:
        if not args.model_id or not args.model_revision:
            raise ValueError("Model identity needs both --model-id and --model-revision")
        signer["model"] = {"id": args.model_id, "revision": args.model_revision}
    evidence = payload.get("local", {}).get("release_evidence") if payload.get("scope") == "local" else None
    decision = publish_shareable_artifact(payload, _read_release_policy(args.policy), args.out, evidence=evidence, signer=signer)
    print(json.dumps(decision.as_dict(), indent=2))
    return 0 if decision.decision == "allow" else 1


def verify_report_command(args: argparse.Namespace) -> int:
    result = verify_report(args.json_report, signing_secret=_secret(args))
    print("PrivateLabBench report verification")
    print(f"Report: {result['path']}")
    print(f"Valid: {result['valid']}")
    print(f"Reason: {result['reason']}")
    print(f"Hash valid: {result['hash_valid']}")
    if result["signature_valid"] is not None:
        print(f"Signature valid: {result['signature_valid']}")
    print(f"Payload SHA256: {result['payload_sha256']}")
    return 0 if result["valid"] else 1


def verify_manifest_command(args: argparse.Namespace) -> int:
    result = verify_run_manifest(args.manifest, signing_secret=_secret(args))
    print("PrivateLabBench manifest verification")
    print(f"Manifest: {result['path']}")
    print(f"Valid: {result['valid']}")
    print(f"Reason: {result['reason']}")
    print(f"Run ID: {result.get('run_id')}")
    print(f"Manifest hash valid: {result['hash_valid']}")
    print(f"Artifact hashes valid: {result['artifacts_valid']}")
    print(f"Report integrity valid: {result['report_valid']}")
    if result["signature_valid"] is not None:
        print(f"Signature valid: {result['signature_valid']}")
    print(f"Payload SHA256: {result['payload_sha256']}")
    return 0 if result["valid"] else 1


def eval_molecules(args: argparse.Namespace) -> int:
    dataset = load_molecule_csv(args.csv_path, target=args.target, smiles_column=args.smiles_column, task_type=args.task_type)
    result = evaluate_random_forest(dataset, test_size=args.test_size, seed=args.seed)
    clean_metrics = dict(result["metrics"])
    privacy_config = make_privacy_config(args)
    reported_metrics = privatize_metrics(clean_metrics, privacy_config)
    report_path = write_markdown_report(args.report, dataset_path=args.csv_path, target=args.target, result=result, clean_metrics=clean_metrics, private_metrics=reported_metrics, privacy_config=privacy_config)
    print("PrivateLabBench molecule evaluation")
    print(f"Task: {dataset.task_type}")
    print(f"Samples: {dataset.n_samples}")
    print(f"Model: {result['model']}")
    print(f"Clean metrics: {summarize_metrics(clean_metrics)}")
    print(f"Reported metrics: {summarize_metrics(reported_metrics)}")
    privacy_risk = dict(result.get("privacy_risk", {}))
    if privacy_risk:
        print("Privacy attack risk: " f"{privacy_risk['risk_level']} " f"(member advantage: {float(privacy_risk['member_advantage']):.4f})")
    print(f"Privacy: {privacy_summary(privacy_config)}")
    print(f"Report saved to: {Path(report_path)}")
    return 0


def eval_federated(args: argparse.Namespace) -> int:
    privacy_config = make_privacy_config(args)
    result = evaluate_federated_directory(args.client_dir, target=args.target, smiles_column=args.smiles_column, task_type=args.task_type, test_size=args.test_size, seed=args.seed, privacy_config=privacy_config)
    report_path = write_federated_markdown_report(args.report, result=result, privacy_config=privacy_config)
    print("PrivateLabBench multi-site evaluation")
    print(f"Sites: {result['n_clients']}")
    print(f"Total samples: {result['total_samples']}")
    print(f"Task type(s): {', '.join(result['task_types'])}")
    print(f"Model(s): {', '.join(result['models'])}")
    for client in result["clients"]:
        print(f"{client.client_id}: {client.n_samples} samples; {summarize_metrics(client.reported_metrics)}")
    print(f"Aggregate clean metrics: {summarize_metrics(result['aggregate_clean_metrics'])}")
    print(f"Aggregate reported metrics: {summarize_metrics(result['aggregate_reported_metrics'])}")
    print(f"Privacy: {privacy_summary(privacy_config)}")
    print(f"Report saved to: {Path(report_path)}")
    return 0


def eval_predictions(args: argparse.Namespace) -> int:
    privacy_config = make_privacy_config(args)
    result = evaluate_prediction_csv(args.csv_path, target=args.target, prediction_column=args.prediction_column, prediction_columns=args.prediction_columns, task_type=args.task_type, sample_id_column=args.sample_id_column, require_sample_id=args.require_sample_id, metadata_columns=args.metadata_columns, slice_columns=args.slice_columns, min_slice_size=args.min_slice_size, class_labels=args.class_labels, split_column=args.split_column)
    clean_metrics = result.metrics
    reported_metrics = privatize_metrics(clean_metrics, privacy_config)
    json_path = write_json_report(args.json_report, report_type="prediction_evaluation", result={"dataset_path": result.dataset_path, "prediction_table_schema": result.schema.as_dict(), "target_column": result.target_column, "prediction_column": result.prediction_column, "prediction_columns": list(result.prediction_columns), "class_labels": list(result.class_labels), "task_type": result.task_type, "n_samples": result.n_samples, "clean_metrics": clean_metrics, "reported_metrics": reported_metrics, "prediction_summary": result.prediction_summary, "slice_metrics": result.slice_metrics, "split_column": result.split_column, "privacy_risk": result.privacy_risk or {}, "sharing_boundary": {"row_level_values_included": False, "aggregate_fields": ["metrics", "prediction_summary", "slice_metrics", "privacy_risk", "schema column names"]}}, privacy_config=privacy_config)
    report_path = write_prediction_markdown_report(args.report, result=result, clean_metrics=clean_metrics, private_metrics=reported_metrics, privacy_config=privacy_config, json_report_path=str(json_path))
    print("PrivateLabBench prediction evaluation")
    print(f"Task: {result.task_type}")
    print(f"Samples: {result.n_samples}")
    print(f"Sample IDs: {result.sample_id_status}")
    if result.schema.slice_columns:
        print(f"Slices: {', '.join(result.schema.slice_columns)}")
    print(f"Clean metrics: {summarize_metrics(clean_metrics)}")
    print(f"Reported metrics: {summarize_metrics(reported_metrics)}")
    if result.privacy_risk:
        print("Privacy attack risk: " f"{result.privacy_risk['risk_level']} " f"(member advantage: {float(result.privacy_risk['member_advantage']):.4f})")
    print(f"Privacy: {privacy_summary(privacy_config)}")
    print(f"Markdown report saved to: {Path(report_path)}")
    print(f"JSON report saved to: {Path(json_path)}")
    print("Local-only report. Use a config with an explicit release policy to export a receipt.")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command in {"evaluate", "init"}:
        return simple_evaluation_command(args)
    if args.command == "audit-design":
        return audit_design_command(args)
    if args.command in {"tdc-prepare", "tdc-evaluate"}:
        return tdc_command(args)
    if args.command == "run":
        return run_from_config(args)
    if args.command in {"list-protocols", "show-protocol"}:
        from privatelabbench.protocols import discover_protocols, resolve_protocol
        if args.command == "list-protocols":
            for protocol in discover_protocols():
                print(f"{protocol.ref}  sha256:{protocol.sha256}")
        else:
            protocol = resolve_protocol(args.protocol)
            print(json.dumps({"identity": protocol.identity(), "definition": protocol.as_dict()}, indent=2, sort_keys=True))
        return 0
    if args.command == "gate":
        return gate_command(args)
    if args.command == "aggregate":
        return aggregate_command(args)
    if args.command == "validate-config":
        return validate_config_command(args)
    if args.command == "list-tasks":
        return list_tasks_command()
    if args.command == "list-privacy-attacks":
        return list_privacy_attacks_command()
    if args.command == "list-packs":
        return list_packs_command()
    if args.command == "run-pack":
        return run_pack_command(args)
    if args.command == "compare":
        from privatelabbench.design_audit import DesignAuditFailure
        try:
            return compare_command(args)
        except DesignAuditFailure as exc:
            print(str(exc))
            return 1
    if args.command == "verify":
        return verify_any_command(args)
    if args.command == "release-check":
        return release_check_command(args)
    if args.command == "sign":
        return sign_command(args)
    if args.command == "verify-report":
        return verify_report_command(args)
    if args.command == "verify-manifest":
        return verify_manifest_command(args)
    if args.command == "eval-molecules":
        return eval_molecules(args)
    if args.command == "eval-federated":
        return eval_federated(args)
    if args.command == "eval-predictions":
        return eval_predictions(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
