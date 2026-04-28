from __future__ import annotations

from pathlib import Path
from typing import Any

from privatelabbench.config import load_config
from privatelabbench.eval.metrics import summarize_metrics
from privatelabbench.privacy.dp import PrivacyConfig
from privatelabbench.reports.json import write_json_report
from privatelabbench.runner import run_config


def compare_configs(config_paths: list[str], *, markdown_path: str, json_path: str) -> dict[str, Any]:
    if len(config_paths) < 2:
        raise ValueError("Comparison requires at least two config files.")

    runs: list[dict[str, Any]] = []
    for path in config_paths:
        config = load_config(path)
        summary = run_config(path)
        metric_payload = summary.get("clean_metrics") or summary.get("aggregate_clean_metrics") or {}
        reported_payload = summary.get("reported_metrics") or summary.get("aggregate_reported_metrics") or {}
        runs.append(
            {
                "config_path": path,
                "project": summary.get("project", config.project),
                "workflow": summary.get("workflow", config.workflow),
                "task_type": summary.get("task_type"),
                "n_samples": summary.get("n_samples", summary.get("total_samples")),
                "clean_metrics": metric_payload,
                "reported_metrics": reported_payload,
                "markdown_report": summary.get("markdown_report"),
                "json_report": summary.get("json_report"),
            }
        )

    metric_names = sorted({name for run in runs for name in run["clean_metrics"].keys()})
    best_by_metric: dict[str, dict[str, object]] = {}
    for metric in metric_names:
        candidates = [run for run in runs if metric in run["clean_metrics"]]
        if not candidates:
            continue
        lower_is_better = any(token in metric.lower() for token in ["mae", "mse", "rmse", "error", "loss"])
        best = sorted(candidates, key=lambda r: float(r["clean_metrics"][metric]), reverse=not lower_is_better)[0]
        best_by_metric[metric] = {
            "project": best["project"],
            "value": float(best["clean_metrics"][metric]),
            "direction": "lower_is_better" if lower_is_better else "higher_is_better",
        }

    payload = {
        "comparison_type": "config_model_comparison",
        "n_runs": len(runs),
        "runs": runs,
        "best_by_metric": best_by_metric,
    }
    write_json_report(
        json_path,
        report_type="model_comparison",
        result=payload,
        privacy_config=PrivacyConfig(mode="none"),
    )
    write_comparison_markdown(markdown_path, payload, json_path=json_path)
    payload["markdown_report"] = markdown_path
    payload["json_report"] = json_path
    return payload


def write_comparison_markdown(output_path: str, payload: dict[str, Any], *, json_path: str) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# PrivateLabBench Model Comparison Report",
        "",
        f"- Compared runs: {payload['n_runs']}",
        f"- JSON report: `{json_path}`",
        "",
        "## Runs",
    ]
    for run in payload["runs"]:
        lines.extend(
            [
                "",
                f"### {run['project']}",
                f"- Config: `{run['config_path']}`",
                f"- Workflow: {run['workflow']}",
                f"- Samples: {run.get('n_samples')}",
                f"- Clean metrics: {summarize_metrics(run['clean_metrics'])}",
                f"- Reported metrics: {summarize_metrics(run['reported_metrics'])}",
                f"- Markdown report: `{run['markdown_report']}`",
                f"- JSON report: `{run['json_report']}`",
            ]
        )
    lines.extend(["", "## Best run by metric"])
    for metric, best in payload["best_by_metric"].items():
        lines.append(f"- {metric}: `{best['project']}` = {float(best['value']):.6f} ({best['direction']})")
    lines.extend([
        "",
        "## Notes",
        "This comparison is designed for local/customer-side benchmarking. Raw scientific rows remain in the execution environment; the comparison report only aggregates run-level metrics and report references.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
