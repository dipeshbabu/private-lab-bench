from __future__ import annotations

import argparse
from pathlib import Path

from privatelabbench.eval.metrics import summarize_metrics
from privatelabbench.eval.predictions import evaluate_prediction_csv
from privatelabbench.federated.evaluator import evaluate_federated_directory
from privatelabbench.models.sklearn_baseline import evaluate_random_forest
from privatelabbench.privacy.dp import PrivacyConfig, privatize_metrics, privacy_summary
from privatelabbench.reports.json import write_json_report
from privatelabbench.reports.markdown import (
    write_federated_markdown_report,
    write_markdown_report,
    write_prediction_markdown_report,
)
from privatelabbench.runner import print_run_summary, run_config
from privatelabbench.tasks.molecules import load_molecule_csv


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
    print(f"Privacy: {privacy_summary(privacy_config)}")
    print(f"Markdown report saved to: {Path(report_path)}")
    print(f"JSON report saved to: {Path(json_path)}")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "run":
        return run_from_config(args)
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
