from __future__ import annotations

from pathlib import Path
from typing import Mapping

from privatelabbench.privacy.dp import PrivacyConfig, privacy_summary


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
    for key, value in clean_metrics.items():
        lines.append(f"- {key}: {value:.6f}")

    lines.extend(["", "## Privacy-preserving reported metrics"])
    for key, value in private_metrics.items():
        lines.append(f"- {key}: {value:.6f}")

    lines.extend(["", "## Privacy mode", privacy_summary(privacy_config), "", "## Dataset shift summary"])
    for key, value in dict(result["shift"]).items():
        lines.append(f"- {key}: {float(value):.6f}")

    lines.extend([
        "",
        "## Notes",
        "PrivateLabBench v0.1 runs evaluation locally and reports only metrics. Raw scientific samples are not uploaded by this CLI.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
