from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from privatelabbench.compare import compare_configs
from privatelabbench.eval.metrics import summarize_metrics
from privatelabbench.eval.predictions import evaluate_prediction_csv
from privatelabbench.federated.evaluator import evaluate_federated_directory
from privatelabbench.models.sklearn_baseline import evaluate_random_forest
from privatelabbench.privacy.dp import PrivacyConfig, privatize_metrics, privacy_summary
from privatelabbench.production import assert_runtime
from privatelabbench.reports.integrity import verify_report
from privatelabbench.reports.manifest import verify_run_manifest
from privatelabbench.reports.json import write_json_report
from privatelabbench.reports.markdown import (
    write_federated_markdown_report,
    write_markdown_report,
    write_prediction_markdown_report,
)
from privatelabbench.runner import print_run_summary, run_config
from privatelabbench.sync import sanitize_summary, sync_payload, write_sanitized_payload
from privatelabbench.tasks.molecules import load_molecule_csv
from privatelabbench.validation import ConfigValidationResult, validate_config


def add_privacy_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--privacy", choices=["none", "dp"], default="none")
    parser.add_argument("--epsilon", type=float, default=8.0)
    parser.add_argument("--sensitivity", type=float, default=1.0)


def add_common_eval_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", required=True, help="Target column name.")
    parser.add_argument("--smiles-column", default="smiles", help="SMILES column name. Default: smiles")
    parser.add_argument("--task-type", choices=["regression", "classification"], default=None)
    parser.add_argument("--test-size", type=float, default=0.25)
    add_privacy_args(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="privatelabbench",
        description="Local-first private evaluation for scientific AI models.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run an evaluation workflow from a YAML config file.")
    run.add_argument("config_path", help="Path to a PrivateLabBench YAML config.")

    validate = sub.add_parser("validate-config", help="Validate a YAML config before running it.")
    validate.add_argument("config_path", help="Path to a PrivateLabBench YAML config.")

    serve = sub.add_parser("serve", help="Start the local PrivateLabBench API server.")
    serve.add_argument("--host", default="127.0.0.1", help="Host interface for the API server.")
    serve.add_argument("--port", type=int, default=8000, help="Port for the API server.")
    serve.add_argument("--reload", action="store_true", help="Enable uvicorn auto-reload for local development.")

    dashboard = sub.add_parser("serve-dashboard", help="Start the hosted-dashboard API for sanitized run metadata.")
    dashboard.add_argument("--host", default="127.0.0.1", help="Host interface for the dashboard API.")
    dashboard.add_argument("--port", type=int, default=8010, help="Port for the dashboard API.")
    dashboard.add_argument("--reload", action="store_true", help="Enable uvicorn auto-reload for local development.")

    compare = sub.add_parser("compare", help="Run multiple configs and generate a model comparison report.")
    compare.add_argument("config_paths", nargs="+", help="Two or more config files to compare.")
    compare.add_argument("--report", default="reports/model_comparison.md")
    compare.add_argument("--json-report", default="reports/model_comparison.json")

    verify = sub.add_parser("verify-report", help="Verify JSON report integrity metadata and optional HMAC signature.")
    verify.add_argument("json_report", help="Path to a PrivateLabBench JSON report.")
    verify.add_argument("--signing-secret", default=None, help="Optional HMAC signing secret. Defaults to PRIVATELABBENCH_SIGNING_SECRET.")

    verify_manifest = sub.add_parser("verify-manifest", help="Verify a run manifest and its bound artifacts.")
    verify_manifest.add_argument("manifest", help="Path to a PrivateLabBench run manifest.")
    verify_manifest.add_argument("--signing-secret", default=None, help="Optional HMAC signing secret. Defaults to PRIVATELABBENCH_SIGNING_SECRET.")

    export = sub.add_parser("export-sanitized", help="Run a config and export dashboard-safe metadata only.")
    export.add_argument("config_path", help="Path to a PrivateLabBench YAML config.")
    export.add_argument("--out", default="reports/sanitized_payload.json", help="Output JSON payload path.")
    export.add_argument("--organization-id", default="local-org", help="Organization id to include in sanitized metadata.")

    sync = sub.add_parser("sync-dashboard", help="Run a config and sync sanitized metrics to a dashboard API.")
    sync.add_argument("config_path", help="Path to a PrivateLabBench YAML config.")
    sync.add_argument("--endpoint", required=True, help="Dashboard API base URL, e.g. http://127.0.0.1:8010")
    sync.add_argument("--api-key", default=None, help="Dashboard API key. Defaults to PRIVATELABBENCH_DASHBOARD_API_KEY.")
    sync.add_argument("--organization-id", default="local-org", help="Organization id to include in sanitized metadata.")
    sync.add_argument("--runner-id", default=None, help="Runner id for signed sync. Defaults to PRIVATELABBENCH_RUNNER_ID.")
    sync.add_argument(
        "--runner-private-key",
        default=None,
        help="Ed25519 private key PEM or path for signed sync. Defaults to PRIVATELABBENCH_RUNNER_PRIVATE_KEY.",
    )

    eval_mol = sub.add_parser("eval-molecules", help="Evaluate a molecular property prediction CSV locally.")
    eval_mol.add_argument("csv_path", help="Path to a CSV containing SMILES and target columns.")
    add_common_eval_args(eval_mol)
    eval_mol.add_argument("--report", default="reports/molecule_eval_report.md")

    eval_fed = sub.add_parser("eval-federated", help="Evaluate multiple private lab CSVs and aggregate reported metrics.")
    eval_fed.add_argument("client_dir", help="Directory containing one CSV per private lab/client.")
    add_common_eval_args(eval_fed)
    eval_fed.add_argument("--report", default="reports/federated_eval_report.md")

    eval_pred = sub.add_parser("eval-predictions", help="Evaluate externally generated model predictions from a CSV.")
    eval_pred.add_argument("csv_path", help="Path to a CSV containing target and prediction columns.")
    eval_pred.add_argument("--target", required=True, help="Target column name.")
    eval_pred.add_argument("--prediction-column", required=True, help="Prediction column name.")
    eval_pred.add_argument("--task-type", choices=["regression", "classification"], default=None)
    eval_pred.add_argument("--split-column", default=None, help="Optional train/test split column for membership-risk scoring.")
    add_privacy_args(eval_pred)
    eval_pred.add_argument("--report", default="reports/prediction_eval_report.md")
    eval_pred.add_argument("--json-report", default="reports/prediction_eval_report.json")
    return parser


def make_privacy_config(args: argparse.Namespace) -> PrivacyConfig:
    return PrivacyConfig(mode=args.privacy, epsilon=args.epsilon, sensitivity=args.sensitivity, seed=args.seed)


def run_from_config(args: argparse.Namespace) -> int:
    summary = run_config(args.config_path)
    print_run_summary(summary)
    return 0


def print_validation_result(result: ConfigValidationResult) -> None:
    print("PrivateLabBench config validation")
    print(f"Config: {result.config_path}")
    if result.project:
        print(f"Project: {result.project}")
    if result.workflow:
        print(f"Workflow: {result.workflow}")
    if result.valid:
        print("Valid: True")
    else:
        print("Valid: False")
    for warning in result.warnings:
        print(f"Warning: {warning}")
    for error in result.errors:
        print(f"Error: {error}")


def validate_config_command(args: argparse.Namespace) -> int:
    result = validate_config(args.config_path)
    print_validation_result(result)
    return 0 if result.valid else 1


def serve_api(args: argparse.Namespace) -> int:
    assert_runtime("api")
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("API dependencies are missing. Install with: pip install -e '.[api]'") from exc
    uvicorn.run("privatelabbench.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def serve_dashboard_api(args: argparse.Namespace) -> int:
    assert_runtime("dashboard")
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("API dependencies are missing. Install with: pip install -e '.[api]'") from exc
    uvicorn.run("privatelabbench.dashboard.api:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def export_sanitized(args: argparse.Namespace) -> int:
    summary = run_config(args.config_path)
    output = write_sanitized_payload(summary, args.out, organization_id=args.organization_id)
    payload = sanitize_summary(summary, organization_id=args.organization_id)
    print("PrivateLabBench sanitized export")
    print(f"Project: {payload.project}")
    print(f"Workflow: {payload.workflow}")
    print(f"Metrics: {summarize_metrics(payload.metrics)}")
    print(f"Payload saved to: {Path(output)}")
    return 0


def sync_dashboard(args: argparse.Namespace) -> int:
    summary = run_config(args.config_path)
    payload = sanitize_summary(summary, organization_id=args.organization_id)
    result = sync_payload(
        payload,
        endpoint=args.endpoint,
        api_key=args.api_key or os.getenv("PRIVATELABBENCH_DASHBOARD_API_KEY"),
        runner_id=args.runner_id,
        runner_private_key=args.runner_private_key,
    )
    print("PrivateLabBench dashboard sync")
    print(f"Project: {payload.project}")
    print(f"Workflow: {payload.workflow}")
    print(f"Synced run id: {result.get('id')}")
    if result.get("signature_verified") is not None:
        print(f"Runner signature verified: {result.get('signature_verified')}")
    return 0


def compare_from_configs(args: argparse.Namespace) -> int:
    result = compare_configs(args.config_paths, markdown_path=args.report, json_path=args.json_report)
    print("PrivateLabBench model comparison")
    print(f"Runs: {result['n_runs']}")
    print(f"Markdown report saved to: {Path(result['markdown_report'])}")
    print(f"JSON report saved to: {Path(result['json_report'])}")
    return 0


def verify_report_command(args: argparse.Namespace) -> int:
    secret = args.signing_secret or os.getenv("PRIVATELABBENCH_SIGNING_SECRET")
    result = verify_report(args.json_report, signing_secret=secret)
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
    secret = args.signing_secret or os.getenv("PRIVATELABBENCH_SIGNING_SECRET")
    result = verify_run_manifest(args.manifest, signing_secret=secret)
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
    private_metrics = privatize_metrics(clean_metrics, privacy_config)

    report_path = write_markdown_report(
        args.report,
        dataset_path=args.csv_path,
        target=args.target,
        result=result,
        clean_metrics=clean_metrics,
        private_metrics=private_metrics,
        privacy_config=privacy_config,
    )

    print("PrivateLabBench molecule evaluation")
    print(f"Task: {dataset.task_type}")
    print(f"Samples: {dataset.n_samples}")
    print(f"Model: {result['model']}")
    print(f"Clean metrics: {summarize_metrics(clean_metrics)}")
    print(f"Reported metrics: {summarize_metrics(private_metrics)}")
    privacy_risk = dict(result.get("privacy_risk", {}))
    if privacy_risk:
        print(
            "Privacy attack risk: "
            f"{privacy_risk['risk_level']} "
            f"(member advantage: {float(privacy_risk['member_advantage']):.4f})"
        )
    print(f"Privacy: {privacy_summary(privacy_config)}")
    print(f"Report saved to: {Path(report_path)}")
    return 0


def eval_federated(args: argparse.Namespace) -> int:
    privacy_config = make_privacy_config(args)
    result = evaluate_federated_directory(
        args.client_dir,
        target=args.target,
        smiles_column=args.smiles_column,
        task_type=args.task_type,
        test_size=args.test_size,
        seed=args.seed,
        privacy_config=privacy_config,
    )
    report_path = write_federated_markdown_report(args.report, result=result, privacy_config=privacy_config)

    print("PrivateLabBench federated evaluation")
    print(f"Clients: {result['n_clients']}")
    print(f"Total samples: {result['total_samples']}")
    print(f"Task type(s): {', '.join(result['task_types'])}")
    print(f"Model(s): {', '.join(result['models'])}")
    print("")
    for client in result["clients"]:
        print(f"{client.client_id}:")
        print(f"  samples: {client.n_samples}")
        print(f"  clean metrics: {summarize_metrics(client.clean_metrics)}")
        print(f"  reported metrics: {summarize_metrics(client.reported_metrics)}")
    print("")
    print(f"Aggregate clean metrics: {summarize_metrics(result['aggregate_clean_metrics'])}")
    print(f"Aggregate reported metrics: {summarize_metrics(result['aggregate_reported_metrics'])}")
    print(f"Privacy: {privacy_summary(privacy_config)}")
    print(f"Report saved to: {Path(report_path)}")
    return 0


def eval_predictions(args: argparse.Namespace) -> int:
    privacy_config = make_privacy_config(args)
    result = evaluate_prediction_csv(
        args.csv_path,
        target=args.target,
        prediction_column=args.prediction_column,
        task_type=args.task_type,
        split_column=args.split_column,
    )
    clean_metrics = result.metrics
    private_metrics = privatize_metrics(clean_metrics, privacy_config)
    json_path = write_json_report(
        args.json_report,
        report_type="prediction_evaluation",
        result={
            "dataset_path": result.dataset_path,
            "target_column": result.target_column,
            "prediction_column": result.prediction_column,
            "task_type": result.task_type,
            "n_samples": result.n_samples,
            "clean_metrics": clean_metrics,
            "reported_metrics": private_metrics,
            "prediction_summary": result.prediction_summary,
            "split_column": result.split_column,
            "privacy_risk": result.privacy_risk or {},
        },
        privacy_config=privacy_config,
    )
    report_path = write_prediction_markdown_report(
        args.report,
        result=result,
        clean_metrics=clean_metrics,
        private_metrics=private_metrics,
        privacy_config=privacy_config,
        json_report_path=str(json_path),
    )

    print("PrivateLabBench prediction evaluation")
    print(f"Task: {result.task_type}")
    print(f"Samples: {result.n_samples}")
    print(f"Clean metrics: {summarize_metrics(clean_metrics)}")
    print(f"Reported metrics: {summarize_metrics(private_metrics)}")
    if result.privacy_risk:
        print(
            "Privacy attack risk: "
            f"{result.privacy_risk['risk_level']} "
            f"(member advantage: {float(result.privacy_risk['member_advantage']):.4f})"
        )
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
    if args.command == "serve":
        return serve_api(args)
    if args.command == "serve-dashboard":
        return serve_dashboard_api(args)
    if args.command == "export-sanitized":
        return export_sanitized(args)
    if args.command == "sync-dashboard":
        return sync_dashboard(args)
    if args.command == "compare":
        return compare_from_configs(args)
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
