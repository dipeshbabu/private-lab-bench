from __future__ import annotations

import argparse
from pathlib import Path

from privatelabbench.eval.metrics import summarize_metrics
from privatelabbench.models.sklearn_baseline import evaluate_random_forest
from privatelabbench.privacy.dp import PrivacyConfig, privatize_metrics, privacy_summary
from privatelabbench.reports.markdown import write_markdown_report
from privatelabbench.tasks.molecules import load_molecule_csv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="privatelabbench",
        description="Local-first private evaluation for scientific AI models.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    eval_mol = sub.add_parser("eval-molecules", help="Evaluate a molecular property prediction CSV locally.")
    eval_mol.add_argument("csv_path", help="Path to a CSV containing SMILES and target columns.")
    eval_mol.add_argument("--target", required=True, help="Target column name.")
    eval_mol.add_argument("--smiles-column", default="smiles", help="SMILES column name. Default: smiles")
    eval_mol.add_argument("--task-type", choices=["regression", "classification"], default=None)
    eval_mol.add_argument("--test-size", type=float, default=0.25)
    eval_mol.add_argument("--seed", type=int, default=13)
    eval_mol.add_argument("--privacy", choices=["none", "dp"], default="none")
    eval_mol.add_argument("--epsilon", type=float, default=8.0)
    eval_mol.add_argument("--sensitivity", type=float, default=1.0)
    eval_mol.add_argument("--report", default="reports/molecule_eval_report.md")
    return parser


def eval_molecules(args: argparse.Namespace) -> int:
    dataset = load_molecule_csv(args.csv_path, target=args.target, smiles_column=args.smiles_column, task_type=args.task_type)
    result = evaluate_random_forest(dataset, test_size=args.test_size, seed=args.seed)
    clean_metrics = dict(result["metrics"])

    privacy_config = PrivacyConfig(mode=args.privacy, epsilon=args.epsilon, sensitivity=args.sensitivity, seed=args.seed)
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


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "eval-molecules":
        return eval_molecules(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
