from __future__ import annotations

from pathlib import Path
from typing import Mapping

from privatelabbench.privacy.dp import PrivacyConfig, privacy_summary


def _format_metric_lines(metrics: Mapping[str, float]) -> list[str]:
    return [f"- {key}: {float(value):.6f}" for key, value in metrics.items()]


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
        f"- Task type: {result['task_type']}",
        "",
        "## Clean local metrics",
    ]
    lines.extend(_format_metric_lines(clean_metrics))

    lines.extend(["", "## Privacy-preserving reported metrics"])
    lines.extend(_format_metric_lines(private_metrics))

    lines.extend(["", "## Privacy mode", privacy_summary(privacy_config), "", "## Dataset shift summary"])
    lines.extend(_format_metric_lines(dict(result["shift"])))

    lines.extend([
        "",
        "## Notes",
        "PrivateLabBench v0.1 runs evaluation locally and reports only metrics. Raw scientific samples are not uploaded by this CLI.",
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
