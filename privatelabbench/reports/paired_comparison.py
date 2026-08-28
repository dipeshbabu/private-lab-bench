from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from privatelabbench.reports.integrity import attach_integrity_metadata


PAIRED_COMPARISON_ARTIFACT_SCHEMA = "paired-comparison-artifact/v1"


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _shareable_comparison(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "comparison_schema": result.get("schema_version"),
        "task_type": result.get("task_type"),
        "class_labels": list(result.get("class_labels", [])),
        "sample_id_column": result.get("sample_id_column"),
        "target_column": result.get("target_column"),
        "n_samples": result.get("n_samples"),
        "alignment": dict(result.get("alignment", {})),
        "model_a": dict(result.get("model_a", {})),
        "model_b": dict(result.get("model_b", {})),
        "metric": result.get("metric"),
        "direction": result.get("direction"),
        "raw_delta_a_minus_b": result.get("raw_delta_a_minus_b"),
        "improvement_a_over_b": result.get("improvement_a_over_b"),
        "paired_interval": dict(result.get("paired_interval", {})),
        "randomization_test": dict(result.get("randomization_test", {})),
        "decision": dict(result.get("decision", {})),
        "slices": dict(result.get("slices", {})),
    }


def build_paired_comparison_artifact(
    *,
    result: Mapping[str, Any],
    path_a: str | Path,
    path_b: str | Path,
    signing_secret: str | None = None,
    comparison_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": PAIRED_COMPARISON_ARTIFACT_SCHEMA,
        "comparison_id": comparison_id or str(uuid4()),
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "scope": "local",
        "shareable": _shareable_comparison(result),
        "local": {
            "sharing": "local_only",
            "inputs": {
                "model_a": {"path": str(path_a), "sha256": _sha256_file(path_a)},
                "model_b": {"path": str(path_b), "sha256": _sha256_file(path_b)},
            },
        },
    }
    return attach_integrity_metadata(payload, signing_secret=signing_secret)


def make_shareable_paired_comparison(
    artifact: Mapping[str, Any], *, signing_secret: str | None = None
) -> dict[str, Any]:
    payload = {
        "schema_version": PAIRED_COMPARISON_ARTIFACT_SCHEMA,
        "comparison_id": artifact.get("comparison_id"),
        "created_at": artifact.get("created_at"),
        "scope": "shareable",
        "shareable": dict(artifact.get("shareable", {})),
    }
    return attach_integrity_metadata(payload, signing_secret=signing_secret)


def render_paired_comparison_markdown(artifact: Mapping[str, Any]) -> str:
    result = artifact["shareable"]
    model_a = result["model_a"]
    model_b = result["model_b"]
    interval = result.get("paired_interval", {})
    randomization = result.get("randomization_test", {})
    decision = result.get("decision", {})
    confidence = interval.get("confidence_level")
    confidence_text = f"{float(confidence):.1%}" if confidence is not None else "n/a"

    lines = [
        "# PrivateLabBench Paired Model Comparison",
        "",
        f"- Comparison schema: `{result.get('comparison_schema')}`",
        f"- Samples: {result.get('n_samples')}",
        f"- Task type: {result.get('task_type')}",
        f"- Alignment: {result.get('alignment', {}).get('status')}",
        f"- Metric: `{result.get('metric')}` ({result.get('direction')})",
        "",
        "## Models",
        f"- Model A: **{model_a.get('name')}** — {result.get('metric')}={float(model_a.get('selected_metric')):.6f}",
        f"- Model B: **{model_b.get('name')}** — {result.get('metric')}={float(model_b.get('selected_metric')):.6f}",
        f"- Raw delta A-B: {float(result.get('raw_delta_a_minus_b')):.6f}",
        f"- Direction-adjusted improvement A over B: {float(result.get('improvement_a_over_b')):.6f}",
        "",
        "## Paired uncertainty",
        f"- Status: {interval.get('status')}",
        f"- Method: {interval.get('method')}",
        f"- Confidence level: {confidence_text}",
    ]
    if interval.get("lower") is not None and interval.get("upper") is not None:
        lines.append(
            f"- Improvement interval: [{float(interval['lower']):.6f}, {float(interval['upper']):.6f}]"
        )
    lines.extend(
        [
            "",
            "## Paired randomization test",
            f"- Status: {randomization.get('status')}",
            f"- Method: {randomization.get('method')}",
            f"- Two-sided p-value: {randomization.get('p_value')}",
            "",
            "## Decision summary",
            f"- Practical threshold: {decision.get('practical_threshold')}",
            f"- Point estimate: {decision.get('point_estimate')}",
            f"- Confidence-interval decision: {decision.get('confidence_interval')}",
        ]
    )
    noninferiority = decision.get("noninferiority")
    if isinstance(noninferiority, Mapping):
        lines.append(
            f"- Noninferiority (margin {noninferiority.get('margin')}): {noninferiority.get('status')}"
        )

    slices = result.get("slices", {})
    if slices:
        lines.extend(["", "## Slice comparison"])
        for column, groups in slices.items():
            lines.extend(["", f"### `{column}`"])
            for group, entry in groups.items():
                lines.append(
                    f"- **{group}** — n={entry.get('n')}, status={entry.get('status')}"
                    + (
                        f", A={float(entry['metric_a']):.6f}, B={float(entry['metric_b']):.6f}, "
                        f"improvement={float(entry['improvement']):.6f}, winner={entry.get('winner')}"
                        if entry.get("status") == "evaluated"
                        else ""
                    )
                )
                slice_interval = entry.get("paired_interval")
                if isinstance(slice_interval, Mapping) and slice_interval.get("lower") is not None:
                    lines.append(
                        f"  - paired CI: [{float(slice_interval['lower']):.6f}, "
                        f"{float(slice_interval['upper']):.6f}]"
                    )

    lines.extend(
        [
            "",
            "## Interpretation",
            "Positive `improvement_a_over_b` always means Model A is better under the selected metric direction.",
            "The paired bootstrap uses the same resampled sample IDs for both models. The randomization test swaps model predictions within matched samples under the exchangeability null.",
            "The practical threshold is user-defined and is distinct from the randomization-test p-value.",
            "",
            "## Sharing boundary",
            "This Markdown is rendered from the independently verifiable `shareable` section only. Prediction-table paths, file hashes, sample IDs, targets, predictions, and row-level metadata are not included.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_paired_comparison_artifacts(
    *,
    json_path: str | Path,
    markdown_path: str | Path,
    result: Mapping[str, Any],
    path_a: str | Path,
    path_b: str | Path,
    signing_secret: str | None = None,
) -> dict[str, Path]:
    local = build_paired_comparison_artifact(
        result=result,
        path_a=path_a,
        path_b=path_b,
        signing_secret=signing_secret,
    )
    shareable = make_shareable_paired_comparison(local, signing_secret=signing_secret)
    local_path = Path(json_path)
    shareable_path = local_path.with_name(f"{local_path.stem}.shareable{local_path.suffix}")
    markdown_output = Path(markdown_path)
    for path in (local_path, shareable_path, markdown_output):
        path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(json.dumps(local, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    shareable_path.write_text(json.dumps(shareable, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_output.write_text(render_paired_comparison_markdown(shareable), encoding="utf-8")
    return {
        "json_report": local_path,
        "shareable_json_report": shareable_path,
        "markdown_report": markdown_output,
    }
