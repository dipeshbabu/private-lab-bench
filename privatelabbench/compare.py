from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

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
    confidence_level: float | None,
    resamples: int | None,
    permutations: int | None,
    seed: int | None,
    min_samples: int | None,
    practical_threshold: float | None,
    noninferiority_margin: float | None,
    include_slice_uncertainty: bool | None,
    min_slice_size: int | None,
    markdown_path: str,
    json_path: str,
    signing_secret: str | None = None,
    release_policy: Mapping[str, Any] | None = None,
    protocol: str | None = None,
    sampling_design: Any = None,
    evaluation_design: Any = None,
    design_audit_options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    options = dict(design_audit_options or {})
    local_path = Path(json_path)
    public_path = local_path.with_name(f"{local_path.stem}.shareable{local_path.suffix}")
    protected = {Path(path_a).resolve(), Path(path_b).resolve(), *([Path(options["training_reference"]).resolve()] if options.get("training_reference") else []), *([Path(protocol).resolve()] if protocol and not protocol.startswith("plb://") else [])}
    outputs = [local_path, public_path, Path(markdown_path), public_path.with_suffix(".release-audit.json"), local_path.parent/".plb-release-ledger.json", local_path.parent/".plb-release.lock", *[local_path.with_name(f"{local_path.stem}_{role}_design_audit.json") for role in ("model_a", "model_b")]]
    if any(output.resolve() in protected for output in outputs):
        raise ValueError("Choose comparison outputs separate from every input")
    local_path.with_name(f"{local_path.stem}.shareable{local_path.suffix}").unlink(missing_ok=True)
    Path(markdown_path).unlink(missing_ok=True)
    settings = {"metric": metric, "confidence_level": confidence_level, "resamples": resamples, "permutations": permutations, "seed": seed, "min_samples": min_samples, "practical_threshold": practical_threshold, "noninferiority_margin": noninferiority_margin, "include_slice_uncertainty": include_slice_uncertainty, "min_slice_size": min_slice_size}
    definition = None
    from privatelabbench.design_audit import EvaluationDesign, DesignAuditFailure, prepare_evaluation
    from privatelabbench.privacy.export import atomic_write_json
    audit_design = EvaluationDesign.from_dict(evaluation_design) if evaluation_design is not None else None
    from privatelabbench.eval.sampling import sampling_design as parse_design
    design = parse_design(sampling_design)
    if protocol is not None:
        from privatelabbench.protocols import _bind, apply_protocol, resolve_protocol
        definition = resolve_protocol(protocol)
        rules = definition.as_dict()
        settings = _bind({key: value for key, value in settings.items() if value is not None}, rules["comparison"], "comparison")
        bound_input = {key: value for key, value in {"task_type": task_type, "class_labels": list(class_labels) if class_labels else None, "slice_columns": list(slice_columns) if slice_columns is not None else None}.items() if value is not None}
        bound_config = apply_protocol({"input": bound_input, **({"sampling_design": design.as_dict()} if design else {}), **({"evaluation_design": audit_design.as_dict()} if audit_design else {})}, definition)
        bound = bound_config["input"]
        design = parse_design(bound_config.get("sampling_design"))
        audit_design = EvaluationDesign.from_dict(bound_config["evaluation_design"]) if bound_config.get("evaluation_design") else None
        task_type, class_labels, slice_columns = bound["task_type"], bound["class_labels"], bound["slice_columns"]
    else:
        settings = {**asdict(PairedComparisonConfig()), **{key: value for key, value in settings.items() if value is not None}}
    config = PairedComparisonConfig(**settings)
    prepared_frames, audit_records = [], []
    if set(options)-{"training_reference", "reference_complete", "failure_mode"} or options.get("failure_mode", "stop") not in {"stop", "local_only"}:
        raise ValueError("Unsupported comparison design-audit options")
    if not audit_design and (options.get("training_reference") or options.get("reference_complete") or options.get("failure_mode", "stop") != "stop"):
        raise ValueError("Training-reference comparison options require an evaluation design")
    if audit_design:
        rules = audit_design.as_dict()
        if rules["sample_id_column"] != sample_id_column or rules["label_column"] not in (None, target):
            raise ValueError("Comparison bindings conflict with the declared evaluation design")
        for role, path in (("model_a", path_a), ("model_b", path_b)):
            audit_path = local_path.with_name(f"{local_path.stem}_{role}_design_audit.json")
            protected = {Path(path_a).resolve(), Path(path_b).resolve(), *([Path(options["training_reference"]).resolve()] if options.get("training_reference") else [])}
            if audit_path.resolve() in protected: raise ValueError("Choose comparison outputs separate from every input")
            audit_path.unlink(missing_ok=True)
            prepared = prepare_evaluation(path, audit_design, training_reference=options.get("training_reference"), reference_complete=options.get("reference_complete", False), additional_identifier_columns=design.metadata_columns if design else ())
            atomic_write_json(audit_path, prepared.artifact)
            audit_records.append({"model_role": role, "path": str(audit_path), "artifact": prepared.artifact})
            if prepared.artifact["audit"]["status"] == "fail" and options.get("failure_mode", "stop") == "stop":
                raise DesignAuditFailure(f"Evaluation design failed before paired scoring; inspect local audit: {audit_path}")
            prepared_frames.append(prepared.frame)
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
        sampling_design=design,
        frame_a=prepared_frames[0] if prepared_frames else None,
        frame_b=prepared_frames[1] if prepared_frames else None,
    )
    if definition is not None:
        result["protocol"] = definition.identity()
        result["protocol_definition"] = definition.as_dict()
    if audit_records:
        result["design_audits"] = [{**record["artifact"]["audit"], "model_role": record["model_role"]} for record in audit_records]
        result["design_audits_local"] = audit_records
    artifacts = write_paired_comparison_artifacts(
        json_path=json_path,
        markdown_path=markdown_path,
        result=result,
        path_a=path_a,
        path_b=path_b,
        signing_secret=signing_secret,
        release_policy=release_policy,
    )
    return {
        **result,
        "markdown_report": str(artifacts["markdown_report"]),
        "json_report": str(artifacts["json_report"]),
        "shareable_json_report": str(artifacts["shareable_json_report"]) if "shareable_json_report" in artifacts else None,
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
