from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from privatelabbench.config import load_config
from privatelabbench.eval.metrics import summarize_metrics
from privatelabbench.eval.paired_comparison import PairedComparisonConfig, compare_prediction_tables
from privatelabbench.privacy.dp import PrivacyConfig
from privatelabbench.reports.json import write_json_report
from privatelabbench.reports.paired_comparison import write_paired_comparison_artifacts
from privatelabbench.runner import run_config


def compare_prediction_files(
    path_a: str,
    path_b: str,
    *,
    target: str,
    prediction_column: str | None,
    prediction_columns: Sequence[str] | None,
    sample_id_column: str,
    task_type: str | None,
    class_labels: Sequence[str] | None,
    slice_columns: Sequence[str] | None,
    model_a_name: str | None,
    model_b_name: str | None,
    metric: str | None,
    confidence_level: float,
    resamples: int,
    permutations: int,
    seed: int,
    min_samples: int,
    practical_threshold: float,
    noninferiority_margin: float | None,
    include_slice_uncertainty: bool,
    min_slice_size: int,
    markdown_path: str,
    json_path: str,
    signing_secret: str | None = None,
) -> dict[str, Any]:
    config = PairedComparisonConfig(
        metric=metric,
        confidence_level=confidence_level,
        resamples=resamples,
        permutations=permutations,
        seed=seed,
        min_samples=min_samples,
        practical_threshold=practical_threshold,
        noninferiority_margin=noninferiority_margin,
        include_slice_uncertainty=include_slice_uncertainty,
        min_slice_size=min_slice_size,
    )
    result = compare_prediction_tables(
        path_a,
        path_b,
        target=target,
        prediction_column=prediction_column,
        prediction_columns=prediction_columns,
        sample_id_column=sample_id_column,
        task_type=task_type,
        class_labels=class_labels,
        slice_columns=slice_columns,
        model_a_name=model_a_name,
        model_b_name=model_b_name,
        config=config,
    )
    artifacts = write_paired_comparison_artifacts(
        json_path=json_path,
        markdown_path=markdown_path,
        result=result,
        path_a=path_a,
        path_b=path_b,
        signing_secret=signing_secret,
    )
    return {
        **result,
        "markdown_report": str(artifacts["markdown_report"]),
        "json_report": str(artifacts["json_report"]),
        "shareable_json_report": str(artifacts["shareable_json_report"]),
    }


def compare_configs(config_paths: list[str], *, markdown_path: str, json_path: str) -> dict[str, Any]:
    """Legacy config-level comparison retained for backwards compatibility."""

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
    lines.extend(
        [
            "",
            "## Notes",
            "This legacy config-level comparison reports run-level metrics. Use paired prediction-table comparison for statistically meaningful candidate-versus-baseline decisions on the same samples.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
