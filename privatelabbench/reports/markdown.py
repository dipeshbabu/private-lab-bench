from __future__ import annotations

from pathlib import Path
from typing import Mapping

from privatelabbench.privacy.dp import PrivacyConfig, privacy_summary


def _format_metric_lines(metrics: Mapping[str, float]) -> list[str]:
    return [f"- {key}: {float(value):.6f}" for key, value in metrics.items()]


def _format_report_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _format_value_lines(values: Mapping[str, object]) -> list[str]:
    return [f"- {key}: {_format_report_value(value)}" for key, value in values.items()]


def _append_uncertainty(lines: list[str], uncertainty: object, *, heading: str = "Statistical uncertainty") -> None:
    if not isinstance(uncertainty, Mapping) or not uncertainty:
        return
    lines.extend(["", f"## {heading}"])
    lines.append(f"- Status: {uncertainty.get('status', 'unknown')}")
    lines.append(f"- Method: {uncertainty.get('method', 'unknown')}")
    if uncertainty.get("confidence_level") is not None:
        lines.append(f"- Confidence level: {float(uncertainty['confidence_level']):.1%}")
    if uncertainty.get("resamples") is not None:
        lines.append(f"- Bootstrap resamples: {uncertainty['resamples']}")
    if uncertainty.get("seed") is not None:
        lines.append(f"- Seed: {uncertainty['seed']}")
    if uncertainty.get("sampling"):
        lines.append(f"- Sampling: {uncertainty['sampling']}")
    intervals = uncertainty.get("metrics", {})
    if isinstance(intervals, Mapping):
        for metric_name, interval_value in intervals.items():
            interval = dict(interval_value) if isinstance(interval_value, Mapping) else {}
            if interval.get("lower") is not None and interval.get("upper") is not None:
                lines.append(
                    f"- {metric_name}: {float(interval.get('estimate')):.6f} "
                    f"[{float(interval['lower']):.6f}, {float(interval['upper']):.6f}] "
                    f"({interval.get('status', 'evaluated')})"
                )
            else:
                lines.append(
                    f"- {metric_name}: {_format_report_value(interval.get('estimate'))} "
                    f"({interval.get('status', 'unavailable')})"
                )


def write_markdown_report(
    output_path: str,
    *,
    dataset_path: str,
    target: str,
    result: Mapping[str, object],
    clean_metrics: Mapping[str, float],
    private_metrics: Mapping[str, float],
    privacy_config: PrivacyConfig,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# PrivateLabBench Evaluation Report",
        "",
        "## Dataset",
        f"- Source: `{dataset_path}`",
        f"- Target column: `{target}`",
        f"- Samples: {result['n_samples']}",
        f"- Train/Test split: {result['n_train']} / {result['n_test']}",
        "",
        "## Model",
        f"- Baseline: {result['model']}",
        f"- Adapter: {result.get('adapter', 'default')}",
        f"- Fingerprint: {result.get('fingerprint', 'hashed_smiles')}",
        f"- Task type: {result['task_type']}",
        "",
        "## Clean local metrics",
    ]
    lines.extend(_format_metric_lines(clean_metrics))
    lines.extend(["", "## Privacy-preserving reported metrics"])
    lines.extend(_format_metric_lines(private_metrics))
    lines.extend(["", "## Privacy mode", privacy_summary(privacy_config), "", "## Dataset shift summary"])
    lines.extend(_format_metric_lines(dict(result["shift"])))
    error_slices = dict(result.get("error_slices", {}))
    if error_slices:
        lines.extend(["", "## Error slices"])
        lines.extend(_format_metric_lines(error_slices))
    privacy_risk = dict(result.get("privacy_risk", {}))
    if privacy_risk:
        lines.extend(["", "## Privacy attack risk"])
        lines.extend(_format_value_lines(privacy_risk))
    lines.extend(["", "## Notes", "PrivateLabBench runs evaluation locally. Raw scientific samples are not uploaded by this CLI."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _append_slice_metrics(lines: list[str], slice_metrics: Mapping[str, object]) -> None:
    if not slice_metrics:
        return
    lines.extend(["", "## Slice metrics"])
    for column, groups_value in slice_metrics.items():
        groups = dict(groups_value)
        lines.extend(["", f"### `{column}`"])
        for group, entry_value in groups.items():
            entry = dict(entry_value)
            lines.append(f"- **{group}** — n={entry.get('n', 0)}, status={entry.get('status', 'unknown')}")
            metrics = entry.get("metrics")
            if isinstance(metrics, Mapping):
                for key, value in metrics.items():
                    lines.append(f"  - {key}: {float(value):.6f}")
            uncertainty = entry.get("uncertainty")
            if isinstance(uncertainty, Mapping) and uncertainty:
                intervals = uncertainty.get("metrics", {})
                if isinstance(intervals, Mapping):
                    for key, interval_value in intervals.items():
                        interval = dict(interval_value) if isinstance(interval_value, Mapping) else {}
                        if interval.get("lower") is not None and interval.get("upper") is not None:
                            lines.append(
                                f"  - {key} CI: [{float(interval['lower']):.6f}, {float(interval['upper']):.6f}]"
                            )


def write_prediction_markdown_report(
    output_path: str,
    *,
    result: object,
    clean_metrics: Mapping[str, float],
    private_metrics: Mapping[str, float],
    privacy_config: PrivacyConfig,
    json_report_path: str | None = None,
    baseline_prediction_column: str | None = None,
    baseline_metrics: Mapping[str, float] | None = None,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = result.schema.as_dict()
    prediction_columns = ", ".join(f"`{column}`" for column in schema["prediction_columns"])
    metadata_columns = ", ".join(f"`{column}`" for column in schema["metadata_columns"]) or "(none)"
    slice_columns = ", ".join(f"`{column}`" for column in schema["slice_columns"]) or "(none)"
    class_labels = ", ".join(str(label) for label in schema["class_labels"]) or "(not applicable)"
    lines = [
        "# PrivateLabBench Prediction Evaluation Report",
        "",
        "## Run summary",
        f"- Source: `{result.dataset_path}`",
        f"- Samples: {result.n_samples}",
        f"- Problem type: {result.task_type}",
        "",
        "## Prediction table schema",
        f"- Schema: `{schema['schema_version']}`",
        f"- Sample ID column: `{schema['sample_id_column']}`" if schema["sample_id_column"] else "- Sample ID column: (not configured)",
        f"- Sample ID status: {schema['sample_id_status']}",
        f"- Target column: `{schema['target_column']}`",
        f"- Prediction column(s): {prediction_columns}",
        f"- Class labels: {class_labels}",
        f"- Metadata columns discovered: {metadata_columns}",
        f"- Slice columns evaluated: {slice_columns}",
        "",
        "## Clean local metrics",
    ]
    lines.extend(_format_metric_lines(clean_metrics))
    _append_uncertainty(lines, result.uncertainty)
    if baseline_prediction_column and baseline_metrics:
        lines.extend(["", "## Baseline comparison", f"- Baseline prediction column: `{baseline_prediction_column}`", ""])
        lines.extend(_format_metric_lines(baseline_metrics))
    lines.extend(["", "## Reported metrics"])
    lines.extend(_format_metric_lines(private_metrics))
    lines.extend(["", "## Prediction summary"])
    lines.extend(_format_metric_lines(result.prediction_summary))
    _append_slice_metrics(lines, result.slice_metrics)
    lines.extend(["", "## Privacy mode", privacy_summary(privacy_config)])
    if result.privacy_risk:
        lines.extend(["", "## Privacy attack risk"])
        lines.extend(_format_value_lines(result.privacy_risk))
    lines.extend([
        "",
        "## Sharing boundary",
        "- Row-level sample IDs, targets, predictions, and metadata values are not written into this aggregate report.",
        "- Confidence intervals are computed locally from row-level data; only aggregate interval bounds and method metadata are reported.",
        "- The report contains aggregate metrics, prediction summaries, slice counts/metrics, privacy-audit summaries, and schema column names.",
        "- The local source path is included for local reproducibility; the shareable receipt removes local-only fields.",
    ])
    if json_report_path:
        lines.extend(["", "## Machine-readable report", f"- JSON report: `{json_report_path}`"])
    lines.extend(["", "## Notes", "This workflow evaluates predictions generated by any model or tool. PrivateLabBench only reads the local prediction table during evaluation."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_federated_markdown_report(
    output_path: str,
    *,
    result: Mapping[str, object],
    privacy_config: PrivacyConfig,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    clients = list(result["clients"])
    lines = [
        "# PrivateLabBench Federated Evaluation Report",
        "",
        "## Run summary",
        f"- Client directory: `{result['directory']}`",
        f"- Target column: `{result['target']}`",
        f"- Clients: {result['n_clients']}",
        f"- Total samples: {result['total_samples']}",
        f"- Task type(s): {', '.join(result['task_types'])}",
        f"- Model(s): {', '.join(result['models'])}",
        "",
        "## Privacy mode",
        privacy_summary(privacy_config),
        "",
        "## Aggregate clean metrics",
    ]
    lines.extend(_format_metric_lines(result["aggregate_clean_metrics"]))
    lines.extend(["", "## Aggregate privacy-preserving reported metrics"])
    lines.extend(_format_metric_lines(result["aggregate_reported_metrics"]))
    lines.extend(["", "## Aggregate dataset shift summary"])
    lines.extend(_format_metric_lines(result["aggregate_shift"]))
    aggregate_release = result.get("aggregate_release")
    if aggregate_release:
        lines.extend(["", "## Aggregate release gate"])
        lines.extend(_format_value_lines(aggregate_release))
    lines.extend(["", "## Per-client results"])
    for client in clients:
        lines.extend([
            "",
            f"### {client.client_id}",
            f"- Source: `{client.dataset_path}`",
            f"- Samples: {client.n_samples}",
            f"- Train/Test split: {client.n_train} / {client.n_test}",
            f"- Task type: {client.task_type}",
            f"- Model: {client.model}",
            "",
            "Clean metrics:",
        ])
        lines.extend(_format_metric_lines(client.clean_metrics))
        lines.append("")
        lines.append("Reported metrics:")
        lines.extend(_format_metric_lines(client.reported_metrics))
        lines.append("")
        lines.append("Shift summary:")
        lines.extend(_format_metric_lines(client.shift))
    lines.extend(["", "## Notes", "This report evaluates multiple local site/lab CSVs independently and combines aggregate metrics. Raw scientific samples are not uploaded by this CLI."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
