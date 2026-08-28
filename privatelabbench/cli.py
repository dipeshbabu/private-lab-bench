from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="privatelabbench", description="Local-first evaluation for scientific machine learning on private data.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run a local evaluation task from a YAML config file.")
    run.add_argument("config_path", help="Path to a PrivateLabBench YAML config.")

    validate = sub.add_parser("validate-config", help="Validate a YAML config before running it.")
    validate.add_argument("config_path", help="Path to a PrivateLabBench YAML config.")

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
    compare.add_argument("--confidence-level", type=float, default=0.95)
    compare.add_argument("--resamples", type=int, default=1000, help="Paired bootstrap resamples.")
    compare.add_argument("--permutations", type=int, default=1000, help="Paired prediction-swap randomization permutations; use 0 to disable.")
    compare.add_argument("--seed", type=int, default=13)
    compare.add_argument("--min-samples", type=int, default=20)
    compare.add_argument("--practical-threshold", type=float, default=0.0, help="Minimum direction-adjusted improvement required for practical superiority.")
    compare.add_argument("--noninferiority-margin", type=float, default=None, help="Optional noninferiority margin for Model A, expressed in selected-metric units after direction adjustment.")
    compare.add_argument("--slice-columns", nargs="*", default=None, help="Metadata columns for paired slice comparison.")
    compare.add_argument("--min-slice-size", type=int, default=5)
    compare.add_argument("--include-slice-uncertainty", action="store_true", help="Also run paired bootstrap intervals inside eligible slices.")
    compare.add_argument("--signing-secret", default=None, help="Optional HMAC secret for local/shareable paired-comparison artifacts.")
    compare.add_argument("--report", default="reports/model_comparison.md")
    compare.add_argument("--json-report", default="reports/model_comparison.json")

    verify_any = sub.add_parser("verify", help="Verify a receipt, run manifest, or JSON report.")
    verify_any.add_argument("artifact", help="Path to a receipt, run manifest, or JSON report.")
    verify_any.add_argument("--signing-secret", default=None, help="Optional HMAC signing secret.")

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
        print(f"Shareable receipt saved to: {shareable}")
        print(f"Receipt Markdown saved to: {markdown}")


def run_from_config(args: argparse.Namespace) -> int:
    summary = run_config(args.config_path)
    print_run_summary(summary)
    _print_receipt_paths(summary)
    return 0


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
    return 0


def compare_command(args: argparse.Namespace) -> int:
    if args.target is None:
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
    )
    interval = result["paired_interval"]
    print("PrivateLabBench paired prediction comparison")
    print(f"Samples: {result['n_samples']}")
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
    print(f"Markdown report saved to: {Path(result['markdown_report'])}")
    print(f"Local JSON artifact saved to: {Path(result['json_report'])}")
    print(f"Shareable JSON artifact saved to: {Path(result['shareable_json_report'])}")
    return 0


def _secret(args: argparse.Namespace) -> str | None:
    return args.signing_secret or os.getenv("PRIVATELABBENCH_SIGNING_SECRET")


def _print_basic_verification(result: dict[str, object]) -> int:
    print(f"Artifact: {result.get('path')}")
    print(f"Valid: {result.get('valid')}")
    print(f"Reason: {result.get('reason')}")
    if result.get("schema_version"):
        print(f"Schema: {result.get('schema_version')}")
    if result.get("scope"):
        print(f"Scope: {result.get('scope')}")
    if result.get("payload_sha256"):
        print(f"Payload SHA256: {result.get('payload_sha256')}")
    return 0 if result.get("valid") else 1


def verify_any_command(args: argparse.Namespace) -> int:
    path = Path(args.artifact)
    payload = json.loads(path.read_text(encoding="utf-8"))
    schema = payload.get("schema_version") if isinstance(payload, dict) else None
    if schema == RECEIPT_SCHEMA_VERSION:
        return _print_basic_verification(verify_receipt(path, signing_secret=_secret(args)))
    if schema == "run-manifest/v0.1":
        result = verify_run_manifest(path, signing_secret=_secret(args))
        result["schema_version"] = schema
        return _print_basic_verification(result)
    result = verify_report(str(path), signing_secret=_secret(args))
    result["schema_version"] = schema
    result["scope"] = payload.get("scope") if isinstance(payload, dict) else None
    return _print_basic_verification(result)


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
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "run":
        return run_from_config(args)
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
        return compare_command(args)
    if args.command == "verify":
        return verify_any_command(args)
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
