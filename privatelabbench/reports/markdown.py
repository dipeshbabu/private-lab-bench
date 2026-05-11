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

    lines.extend([
        "",
        "## Notes",
        "PrivateLabBench runs evaluation locally and reports only metrics. Raw scientific samples are not uploaded by this CLI.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_prediction_markdown_report(
    output_path: str,
    *,
    result: object,
    clean_metrics: Mapping[str, float],
    private_metrics: Mapping[str, float],
    privacy_config: PrivacyConfig,
    json_report_path: str | None = None,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# PrivateLabBench Prediction Evaluation Report",
        "",
        "## Dataset",
        f"- Source: `{result.dataset_path}`",
        f"- Target column: `{result.target_column}`",
        f"- Prediction column: `{result.prediction_column}`",
        f"- Samples: {result.n_samples}",
        f"- Task type: {result.task_type}",
        "",
        "## Clean local metrics",
    ]
    lines.extend(_format_metric_lines(clean_metrics))
    lines.extend(["", "## Privacy-preserving reported metrics"])
    lines.extend(_format_metric_lines(private_metrics))
    lines.extend(["", "## Prediction summary"])
    lines.extend(_format_metric_lines(result.prediction_summary))
    lines.extend(["", "## Privacy mode", privacy_summary(privacy_config)])
    if json_report_path:
        lines.extend(["", "## Machine-readable report", f"- JSON report: `{json_report_path}`"])
    lines.extend([
        "",
        "## Notes",
        "This workflow evaluates externally generated model predictions. It is designed for customer-owned models where PrivateLabBench only sees local targets and predictions during local execution.",
    ])
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

    lines.extend([
        "",
        "## Notes",
        "This report simulates a multi-lab private evaluation workflow. Each client CSV is evaluated independently, then only aggregate metrics and summaries are combined. Raw scientific samples are not uploaded by this CLI.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
