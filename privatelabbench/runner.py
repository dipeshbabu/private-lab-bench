from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from privatelabbench.adapters.sklearn_adapter import build_molecule_adapter
from privatelabbench.audit import write_audit_event
from privatelabbench.config import RunnerConfig, load_config, required, section
from privatelabbench.core.registry import (
    discover_entrypoint_tasks,
    get_task,
    has_task,
    register_task,
)
from privatelabbench.eval.metrics import summarize_metrics
from privatelabbench.eval.predictions import (
    evaluate_prediction_csv,
    evaluate_prediction_table,
)
from privatelabbench.eval.uncertainty import BootstrapConfig
from privatelabbench.federated.evaluator import evaluate_federated_directory
from privatelabbench.identity import benchmark_metadata, runner_metadata
from privatelabbench.privacy.dp import PrivacyConfig, privacy_summary, privatize_metrics
from privatelabbench.privacy.policy import PrivacyRiskPolicy, evaluate_privacy_gate
from privatelabbench.privacy.release import (
    AggregateReleasePolicy,
    evaluate_aggregate_release,
)
from privatelabbench.reports.json import write_json_report
from privatelabbench.reports.manifest import sha256_file, write_run_manifest
from privatelabbench.reports.markdown import (
    write_federated_markdown_report,
    write_markdown_report,
    write_prediction_markdown_report,
)
from privatelabbench.tasks.molecules import load_molecule_csv


def _privacy_config(config: RunnerConfig) -> PrivacyConfig:
    privacy = section(config, "privacy")
    return PrivacyConfig(
        mode=str(privacy.get("mode", "none")),
        epsilon=privacy.get("epsilon", 8.0),
        sensitivity=privacy.get("sensitivity", 1.0),
        seed=privacy.get("seed", 13),
    )


def _uncertainty_config(config: RunnerConfig) -> BootstrapConfig:
    uncertainty = section(config, "uncertainty")
    return BootstrapConfig(
        enabled=bool(uncertainty.get("enabled", False)),
        method=str(uncertainty.get("method", "percentile_bootstrap")),
        confidence_level=float(uncertainty.get("confidence_level", 0.95)),
        resamples=int(uncertainty.get("resamples", 1000)),
        seed=int(uncertainty.get("seed", 13)),
        min_samples=int(uncertainty.get("min_samples", 20)),
        include_slices=bool(uncertainty.get("include_slices", False)),
    )


def _report_path(config: RunnerConfig, key: str, default: str) -> str:
    report = section(config, "report")
    return str(report.get(key, default))


def _input_path(config: RunnerConfig, value: str) -> str:
    from privatelabbench.core.local_io import resolve_input_path

    return str(resolve_input_path(value, config_path=config.config_path))


def _signing_secret(config: RunnerConfig) -> str | None:
    report = section(config, "report")
    secret = report.get("signing_secret") or os.getenv("PRIVATELABBENCH_SIGNING_SECRET")
    return str(secret) if secret else None


def _audit_path(config: RunnerConfig) -> str:
    audit = section(config, "audit")
    return str(audit.get("path", f"reports/{config.project}_audit.jsonl"))


def _manifest_path(config: RunnerConfig) -> str:
    return _report_path(
        config, "manifest", f"reports/{config.project}_{config.workflow}_manifest.json"
    )


def _write_audit(config: RunnerConfig, summary: dict[str, Any]) -> str:
    audit_path = _audit_path(config)
    write_audit_event(
        audit_path,
        event_type="evaluation_completed",
        payload={
            "project": config.project,
            "task": config.task_id,
            "markdown_report": summary.get("markdown_report"),
            "json_report": summary.get("json_report"),
            "privacy": summary.get("privacy"),
        },
    )
    return audit_path


def _privacy_risk_policy(config: RunnerConfig) -> PrivacyRiskPolicy:
    privacy = section(config, "privacy")
    risk_policy = privacy.get("risk_policy")
    if risk_policy is not None and not isinstance(risk_policy, dict):
        raise ValueError("privacy.risk_policy must be a mapping when provided.")
    return PrivacyRiskPolicy.from_config(risk_policy)


def _aggregate_release_policy(config: RunnerConfig) -> AggregateReleasePolicy:
    privacy = section(config, "privacy")
    aggregate_policy = privacy.get("aggregate_policy")
    if aggregate_policy is not None and not isinstance(aggregate_policy, dict):
        raise ValueError("privacy.aggregate_policy must be a mapping when provided.")
    return AggregateReleasePolicy.from_config(aggregate_policy)


def _identity_metadata(config: RunnerConfig) -> dict[str, Any]:
    identity = {**benchmark_metadata(config), **runner_metadata(config)}
    if config.protocol is not None:
        identity["evaluation_protocol"] = config.protocol.identity()
        identity["protocol_definition"] = config.protocol.as_dict()
    return identity


def _string_list(value: Any, *, key: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a YAML list")
    return [str(item) for item in value]


def _selected_metric_names(config: RunnerConfig):
    if config.protocol is not None:
        return config.protocol.as_dict()["metrics"]
    evaluation = section(config, "evaluation")
    return evaluation.get(
        "metrics",
        ["spearman"] if evaluation.get("primary_metric") == "spearman" else None,
    )


def _evaluation_group(config: RunnerConfig):
    return (
        config.protocol.as_dict().get("evaluation_group")
        if config.protocol is not None
        else None
    )


def _baseline_prediction_metrics(
    config: RunnerConfig,
    *,
    path: str,
    target: str,
    task_type: Any,
    split_column: Any,
    sample_id_column: str | None,
) -> tuple[str | None, dict[str, float] | None]:
    input_cfg = section(config, "input")
    baseline_column = input_cfg.get("baseline_prediction_column")
    if not baseline_column:
        return None, None
    if str(task_type or "").lower() == "multiclass" or input_cfg.get(
        "prediction_columns"
    ):
        raise ValueError(
            "baseline_prediction_column currently supports regression and binary classification only"
        )
    evaluator = (
        evaluate_prediction_table
        if config.prepared_input is not None
        else evaluate_prediction_csv
    )
    source = config.prepared_input if config.prepared_input is not None else path
    baseline = evaluator(
        source,
        **({"dataset_path": path} if config.prepared_input is not None else {}),
        target=target,
        prediction_column=str(baseline_column),
        task_type=task_type,
        class_labels=input_cfg.get("class_labels") or None,
        metric_names=_selected_metric_names(config),
        evaluation_group=_evaluation_group(config),
        sample_id_column=sample_id_column,
        require_sample_id=False,
        sampling_design=config.raw.get("sampling_design"),
        split_column=str(split_column) if split_column else None,
    )
    return str(baseline_column), baseline.metrics


def _attach_report_identity(
    summary: dict[str, Any], json_path: Path, identity: dict[str, Any]
) -> dict[str, Any]:
    report = json.loads(json_path.read_text(encoding="utf-8"))
    integrity = report.get("integrity", {}) if isinstance(report, dict) else {}
    summary.update(identity)
    summary["run_id"] = str(report.get("run_id", ""))
    summary["report_payload_sha256"] = str(integrity.get("payload_sha256", ""))
    summary["report_signed"] = bool(integrity.get("signed", False))
    return summary


def run_prediction_workflow(config: RunnerConfig) -> dict[str, Any]:
    input_cfg = section(config, "input")
    path = _input_path(config, str(required(input_cfg, "path", section_name="input")))
    target = str(required(input_cfg, "target_column", section_name="input"))
    prediction_column = input_cfg.get("prediction_column")
    prediction_columns = _string_list(
        input_cfg.get("prediction_columns"), key="input.prediction_columns"
    )
    if prediction_column is None and not prediction_columns:
        raise ValueError(
            "Missing required config value: input.prediction_column or input.prediction_columns"
        )
    task_type = input_cfg.get("task_type")
    sample_id_column_value = input_cfg.get("sample_id_column", "sample_id")
    sample_id_column = (
        str(sample_id_column_value)
        if sample_id_column_value not in (None, "")
        else None
    )
    require_sample_id = bool(input_cfg.get("require_sample_id", False))
    metadata_columns = _string_list(
        input_cfg.get("metadata_columns"), key="input.metadata_columns"
    )
    slice_columns = _string_list(
        input_cfg.get("slice_columns"), key="input.slice_columns"
    )
    class_labels = _string_list(input_cfg.get("class_labels"), key="input.class_labels")
    min_slice_size = int(input_cfg.get("min_slice_size", 2))
    split_column = input_cfg.get("split_column")

    validation = config.validation_context
    submission_context = {}
    if "benchmark_submission" in config.raw:
        from privatelabbench.hidden_benchmarks import submission_identity

        submission_context = submission_identity(config.raw["benchmark_submission"])
    baseline_prediction_column, baseline_metrics = _baseline_prediction_metrics(
        config,
        path=path,
        target=target,
        task_type=task_type,
        split_column=split_column,
        sample_id_column=sample_id_column,
    )
    privacy_config = _privacy_config(config)
    uncertainty_config = _uncertainty_config(config)
    uncertainty_config.validate()
    identity = _identity_metadata(config)
    if validation is not None:
        identity["external_validation"] = validation

    evaluator = (
        evaluate_prediction_table
        if config.prepared_input is not None
        else evaluate_prediction_csv
    )
    source = config.prepared_input if config.prepared_input is not None else path
    result = evaluator(
        source,
        **({"dataset_path": path} if config.prepared_input is not None else {}),
        target=target,
        prediction_column=str(prediction_column)
        if prediction_column is not None
        else None,
        prediction_columns=prediction_columns or None,
        task_type=str(task_type) if task_type else None,
        sample_id_column=sample_id_column,
        require_sample_id=require_sample_id,
        metadata_columns=metadata_columns or None,
        slice_columns=slice_columns or None,
        min_slice_size=min_slice_size,
        class_labels=class_labels or None,
        metric_names=_selected_metric_names(config),
        evaluation_group=_evaluation_group(config),
        split_column=str(split_column) if split_column else None,
        uncertainty_config=uncertainty_config,
        sampling_design=config.raw.get("sampling_design"),
    )
    clean_metrics = result.metrics
    reported_metrics = privatize_metrics(clean_metrics, privacy_config)
    privacy_gate = evaluate_privacy_gate(
        result.privacy_risk, _privacy_risk_policy(config)
    )

    json_path = write_json_report(
        _report_path(config, "json", f"reports/{config.project}_prediction_eval.json"),
        report_type="prediction_evaluation",
        result={
            "project": config.project,
            "dataset_path": result.dataset_path,
            "prediction_table_schema": result.schema.as_dict(),
            "target_column": result.target_column,
            "prediction_column": result.prediction_column,
            "prediction_columns": list(result.prediction_columns),
            "class_labels": list(result.class_labels),
            "task_type": result.task_type,
            "n_samples": result.n_samples,
            "clean_metrics": clean_metrics,
            "reported_metrics": reported_metrics,
            "uncertainty": result.uncertainty or {},
            "prediction_summary": result.prediction_summary,
            "slice_metrics": result.slice_metrics,
            "baseline_prediction_column": baseline_prediction_column,
            "baseline_metrics": baseline_metrics or {},
            "external_validation": validation or {},
            "benchmark_submission": submission_context,
            "split_column": result.split_column,
            "privacy_risk": result.privacy_risk or {},
            "privacy_gate": privacy_gate,
            "sharing_boundary": {
                "row_level_values_included": False,
                "aggregate_fields": [
                    "metrics",
                    "uncertainty",
                    "prediction_summary",
                    "slice_metrics",
                    "privacy_risk",
                    "schema column names",
                ],
            },
        },
        privacy_config=privacy_config,
        extra=identity,
        config_snapshot=config.raw,
        signing_secret=_signing_secret(config),
    )
    markdown_path = write_prediction_markdown_report(
        _report_path(
            config, "markdown", f"reports/{config.project}_prediction_eval.md"
        ),
        result=result,
        clean_metrics=clean_metrics,
        private_metrics=reported_metrics,
        privacy_config=privacy_config,
        json_report_path=str(json_path),
        baseline_prediction_column=baseline_prediction_column,
        baseline_metrics=baseline_metrics,
    )
    summary = {
        "project": config.project,
        "workflow": config.workflow,
        "task": config.task_id,
        "task_type": result.task_type,
        "n_samples": result.n_samples,
        "clean_metrics": clean_metrics,
        "reported_metrics": reported_metrics,
        "uncertainty": result.uncertainty or {},
        "sample_id_status": result.sample_id_status,
        "slice_columns": list(result.schema.slice_columns),
        "baseline_prediction_column": baseline_prediction_column,
        "baseline_metrics": baseline_metrics or {},
        "markdown_report": str(markdown_path),
        "json_report": str(json_path),
        "privacy": privacy_summary(privacy_config),
    }
    if result.privacy_risk:
        summary["privacy_risk_level"] = result.privacy_risk.get("risk_level")
        summary["privacy_attack_auc"] = result.privacy_risk.get("attack_auc")
        summary["privacy_member_advantage"] = result.privacy_risk.get(
            "member_advantage"
        )
        summary["split_column"] = result.split_column
    summary["privacy_gate_status"] = privacy_gate["status"]
    summary["privacy_gate_publishable"] = privacy_gate["publishable"]
    return _attach_report_identity(summary, json_path, identity)


def run_molecule_workflow(config: RunnerConfig) -> dict[str, Any]:
    input_cfg = section(config, "input")
    model_cfg = section(config, "model")
    path = _input_path(config, str(required(input_cfg, "path", section_name="input")))
    target = str(required(input_cfg, "target_column", section_name="input"))
    smiles_column = str(input_cfg.get("smiles_column", "smiles"))
    task_type = input_cfg.get("task_type")
    test_size = float(input_cfg.get("test_size", 0.25))
    seed = int(section(config, "privacy").get("seed", 13))
    privacy_config = _privacy_config(config)
    identity = _identity_metadata(config)

    dataset = load_molecule_csv(
        path, target=target, smiles_column=smiles_column, task_type=task_type
    )
    adapter = build_molecule_adapter(model_cfg)
    result = adapter.evaluate(dataset, test_size=test_size, seed=seed)
    clean_metrics = dict(result["metrics"])
    reported_metrics = privatize_metrics(clean_metrics, privacy_config)
    privacy_gate = evaluate_privacy_gate(
        result.get("privacy_risk"), _privacy_risk_policy(config)
    )

    markdown_path = write_markdown_report(
        _report_path(config, "markdown", f"reports/{config.project}_molecule_eval.md"),
        dataset_path=path,
        target=target,
        result=result,
        clean_metrics=clean_metrics,
        private_metrics=reported_metrics,
        privacy_config=privacy_config,
    )
    json_path = write_json_report(
        _report_path(config, "json", f"reports/{config.project}_molecule_eval.json"),
        report_type="molecule_evaluation",
        result={
            "project": config.project,
            "dataset_path": path,
            "target_column": target,
            "task_type": result["task_type"],
            "n_samples": result["n_samples"],
            "n_train": result["n_train"],
            "n_test": result["n_test"],
            "model": result["model"],
            "adapter": result.get("adapter"),
            "fingerprint": result.get("fingerprint"),
            "clean_metrics": clean_metrics,
            "reported_metrics": reported_metrics,
            "shift": result["shift"],
            "error_slices": result.get("error_slices", {}),
            "privacy_risk": result.get("privacy_risk", {}),
            "privacy_gate": privacy_gate,
        },
        privacy_config=privacy_config,
        extra=identity,
        config_snapshot=config.raw,
        signing_secret=_signing_secret(config),
    )
    summary = {
        "project": config.project,
        "workflow": config.workflow,
        "task": config.task_id,
        "task_type": result["task_type"],
        "n_samples": result["n_samples"],
        "clean_metrics": clean_metrics,
        "reported_metrics": reported_metrics,
        "markdown_report": str(markdown_path),
        "json_report": str(json_path),
        "privacy": privacy_summary(privacy_config),
    }
    privacy_risk = dict(result.get("privacy_risk", {}))
    if privacy_risk:
        summary["privacy_risk_level"] = privacy_risk.get("risk_level")
        summary["privacy_attack_auc"] = privacy_risk.get("attack_auc")
        summary["privacy_member_advantage"] = privacy_risk.get("member_advantage")
    summary["privacy_gate_status"] = privacy_gate["status"]
    summary["privacy_gate_publishable"] = privacy_gate["publishable"]
    return _attach_report_identity(summary, json_path, identity)


def run_federated_workflow(config: RunnerConfig) -> dict[str, Any]:
    input_cfg = section(config, "input")
    client_dir = _input_path(
        config, str(required(input_cfg, "client_dir", section_name="input"))
    )
    target = str(required(input_cfg, "target_column", section_name="input"))
    smiles_column = str(input_cfg.get("smiles_column", "smiles"))
    task_type = input_cfg.get("task_type")
    test_size = float(input_cfg.get("test_size", 0.25))
    seed = int(section(config, "privacy").get("seed", 13))
    privacy_config = _privacy_config(config)
    identity = _identity_metadata(config)

    result = evaluate_federated_directory(
        client_dir,
        target=target,
        smiles_column=smiles_column,
        task_type=task_type,
        test_size=test_size,
        seed=seed,
        privacy_config=privacy_config,
    )
    aggregate_release = evaluate_aggregate_release(
        n_clients=int(result["n_clients"]),
        total_samples=int(result["total_samples"]),
        client_sample_counts=[client.n_samples for client in result["clients"]],
        policy=_aggregate_release_policy(config),
    )
    result["aggregate_release"] = aggregate_release
    markdown_path = write_federated_markdown_report(
        _report_path(config, "markdown", f"reports/{config.project}_federated_eval.md"),
        result=result,
        privacy_config=privacy_config,
    )
    json_path = write_json_report(
        _report_path(config, "json", f"reports/{config.project}_federated_eval.json"),
        report_type="federated_evaluation",
        result={
            "project": config.project,
            "directory": result["directory"],
            "target": result["target"],
            "n_clients": result["n_clients"],
            "total_samples": result["total_samples"],
            "task_types": result["task_types"],
            "models": result["models"],
            "clients": result["clients"],
            "aggregate_clean_metrics": result["aggregate_clean_metrics"],
            "aggregate_reported_metrics": result["aggregate_reported_metrics"],
            "aggregate_shift": result["aggregate_shift"],
            "aggregate_release": aggregate_release,
        },
        privacy_config=privacy_config,
        extra=identity,
        config_snapshot=config.raw,
        signing_secret=_signing_secret(config),
    )
    summary = {
        "project": config.project,
        "workflow": config.workflow,
        "task": config.task_id,
        "n_clients": result["n_clients"],
        "total_samples": result["total_samples"],
        "aggregate_clean_metrics": result["aggregate_clean_metrics"],
        "aggregate_reported_metrics": result["aggregate_reported_metrics"],
        "markdown_report": str(markdown_path),
        "json_report": str(json_path),
        "privacy": privacy_summary(privacy_config),
        "aggregate_release_status": aggregate_release["status"],
        "aggregate_release_publishable": aggregate_release["publishable"],
    }
    return _attach_report_identity(summary, json_path, identity)


def ensure_builtin_tasks_registered() -> None:
    builtins = (
        (
            "predictions",
            run_prediction_workflow,
            "Evaluate a local table of targets and externally generated predictions.",
        ),
        (
            "tabular",
            run_prediction_workflow,
            "Domain-neutral tabular prediction evaluation using the prediction-table interface.",
        ),
        (
            "molecules",
            run_molecule_workflow,
            "Evaluate the built-in molecular property baseline and diagnostics.",
        ),
        (
            "multi-site",
            run_federated_workflow,
            "Evaluate multiple local lab/site CSVs and aggregate metrics.",
        ),
        (
            "federated",
            run_federated_workflow,
            "Legacy alias for the multi-site evaluation task.",
        ),
    )
    for task_id, task_runner, description in builtins:
        if not has_task(task_id):
            register_task(task_id, task_runner, description=description)


def _prepare_design_audit(
    config: RunnerConfig, path: str, *, reference_cohort: bool = False
):
    from privatelabbench.design_audit import (
        DesignAuditFailure,
        EvaluationDesign,
        prepare_evaluation,
    )
    from privatelabbench.eval.sampling import sampling_design
    from privatelabbench.privacy.export import atomic_write_json

    rules = EvaluationDesign.from_dict(config.raw["evaluation_design"])
    options = section(config, "design_audit")
    if set(options) - {
        "training_reference",
        "reference_complete",
        "failure_mode",
    } or options.get("failure_mode", "stop") not in {"stop", "local_only"}:
        raise ValueError("Unsupported design_audit options or failure_mode")
    reference = (
        _input_path(config, str(options["training_reference"]))
        if options.get("training_reference")
        else None
    )
    manifest = Path(_manifest_path(config))
    stem = manifest.stem.removesuffix("_manifest")
    audit_path = manifest.with_name(
        f"{stem}_{'reference_' if reference_cohort else ''}design_audit.json"
    )
    protected = {
        Path(path).resolve(),
        *([Path(reference).resolve()] if reference else []),
        *([Path(config.config_path).resolve()] if config.config_path else []),
    }
    if audit_path.resolve() in protected:
        raise ValueError("Design-audit output must be separate from every input")
    audit_path.unlink(missing_ok=True)
    design = sampling_design(config.raw.get("sampling_design"))
    identifiers = tuple(design.metadata_columns) if design else ()
    group = _evaluation_group(config)
    if group:
        identifiers = (*identifiers, group["column"])
    prepared = prepare_evaluation(
        path,
        rules,
        training_reference=reference,
        reference_complete=options.get("reference_complete", False),
        additional_identifier_columns=identifiers,
    )
    atomic_write_json(audit_path, prepared.artifact)
    if (
        prepared.artifact["audit"]["status"] == "fail"
        and options.get("failure_mode", "stop") == "stop"
    ):
        raise DesignAuditFailure(
            f"Evaluation design failed before scoring; inspect local audit: {audit_path}"
        )
    input_cfg = section(config, "input")
    required_columns = [
        input_cfg["target_column"],
        *(input_cfg.get("prediction_columns") or [input_cfg.get("prediction_column")]),
        *(
            [input_cfg["baseline_prediction_column"]]
            if input_cfg.get("baseline_prediction_column")
            else []
        ),
        *([input_cfg["split_column"]] if input_cfg.get("split_column") else []),
    ]
    if any(
        column is None or column not in prepared.frame for column in required_columns
    ):
        raise ValueError(
            "The declared evaluation table is missing target/prediction columns"
        )
    if prepared.frame[required_columns].isna().any().any():
        raise ValueError(
            "Declared eligibility leaves missing targets/predictions; repair data or declare exclusions before scoring"
        )
    record = {"path": str(audit_path), "artifact": prepared.artifact}
    return prepared, record


def _attach_design_audits(config: RunnerConfig, summary: dict[str, Any]) -> None:
    from privatelabbench.design_audit import render_design_audit
    from privatelabbench.reports.integrity import attach_integrity_metadata

    report_path = Path(summary["json_report"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    for index, record in enumerate(config.design_audits):
        key = "design_audit" if index == 0 else "reference_design_audit"
        report["result"][key] = record["artifact"]["audit"]
        summary[key] = record["artifact"]["audit"]
        if summary.get("markdown_report"):
            with Path(summary["markdown_report"]).open("a", encoding="utf-8") as handle:
                handle.write(
                    "\n"
                    + render_design_audit(
                        record["artifact"]["audit"],
                        heading="Reference-cohort design audit"
                        if index
                        else "Evaluation-design audit",
                    )
                )
    failed = any(
        record["artifact"]["audit"]["status"] == "fail"
        for record in config.design_audits
    )
    report["result"]["design_release_gate"] = {
        "status": "fail" if failed else "pass",
        "publishable": not failed,
        "scope": "supported_violation_gate_only",
    }
    report.setdefault("extra", {})["design_audits_local"] = list(config.design_audits)
    report = attach_integrity_metadata(report, signing_secret=_signing_secret(config))
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _attach_report_identity(summary, report_path, {})


def _validate_run_paths(config: RunnerConfig) -> None:
    """Protect source data and definitions before invalidating or writing reports."""
    from privatelabbench.core.local_io import validate_output_paths
    from privatelabbench.reports.manifest import _receipt_output_paths

    inputs = [*config.definition_paths, config.config_path]
    input_cfg = section(config, "input")
    for value in (
        input_cfg.get("path"),
        section(config, "diagnostics").get("reference_path"),
        section(config, "design_audit").get("training_reference"),
    ):
        if value:
            inputs.append(_input_path(config, str(value)))
    if input_cfg.get("client_dir"):
        inputs.extend(
            Path(_input_path(config, str(input_cfg["client_dir"]))).glob("*.csv")
        )

    manifest = Path(_manifest_path(config))
    receipt, public, markdown = _receipt_output_paths(manifest)
    outputs = [
        manifest,
        receipt,
        public,
        markdown,
        _audit_path(config),
        public.with_suffix(".release-audit.json"),
        public.parent / ".plb-release-ledger.json",
        public.parent / ".plb-release.lock",
    ]
    report_kind = {
        "predictions": "prediction",
        "tabular": "prediction",
        "molecules": "molecule",
        "multi-site": "federated",
        "federated": "federated",
    }.get(config.task_id)
    for key, suffix in (("json", "json"), ("markdown", "md")):
        if report_kind:
            outputs.append(
                _report_path(
                    config, key, f"reports/{config.project}_{report_kind}_eval.{suffix}"
                )
            )
        elif section(config, "report").get(key):
            outputs.append(section(config, "report")[key])
    if config.raw.get("evaluation_design") is not None:
        stem = manifest.stem.removesuffix("_manifest")
        outputs.append(manifest.with_name(f"{stem}_design_audit.json"))
        if "diagnostics" in config.raw:
            outputs.append(manifest.with_name(f"{stem}_reference_design_audit.json"))
    validate_output_paths(inputs, outputs)


def run_config(
    config_path: str, *, protocol_override: str | None = None
) -> dict[str, Any]:
    config = load_config(config_path, protocol_override=protocol_override)
    _validate_run_paths(config)
    # Invalidate a previous export before any evaluation or plugin can fail.
    from privatelabbench.reports.manifest import _receipt_output_paths

    _, previous_shareable, previous_markdown = _receipt_output_paths(
        Path(_manifest_path(config))
    )
    previous_shareable.unlink(missing_ok=True)
    previous_markdown.unlink(missing_ok=True)
    _privacy_config(config).validate()
    _privacy_risk_policy(config)
    _aggregate_release_policy(config)
    ensure_builtin_tasks_registered()
    discover_entrypoint_tasks()
    task = get_task(config.task_id)
    if (
        config.raw.get("sampling_design") is not None
        and task.source == "builtin"
        and config.task_id not in {"predictions", "tabular"}
    ):
        raise ValueError(
            "Declared sampling designs currently require a prediction-table task"
        )
    if config.raw.get("evaluation_design") is not None:
        if config.task_id not in {"predictions", "tabular"}:
            raise ValueError(
                "Evaluation-design filtering currently requires a prediction-table task"
            )
        prepared, record = _prepare_design_audit(
            config, _input_path(config, str(section(config, "input")["path"]))
        )
        config = replace(config, prepared_input=prepared.frame, design_audits=(record,))
    if "external_validation" in config.raw:
        from privatelabbench.external_validation import prepare_validation

        frame, context = prepare_validation(
            config, _input_path(config, str(section(config, "input")["path"]))
        )
        config = replace(config, prepared_input=frame, validation_context=context)
    summary = task.runner(config)
    if "diagnostics" in config.raw:
        from privatelabbench.eval.degradation import diagnose_shift, render_degradation
        from privatelabbench.reports.integrity import attach_integrity_metadata

        if config.task_id not in {"predictions", "tabular"}:
            raise ValueError(
                "Reference/current diagnostics require a prediction-table task"
            )
        diagnostics = section(config, "diagnostics")
        allowed = {
            "reference_path",
            "independent_cohorts",
            "practical_thresholds",
            "prevalence_threshold",
            "numeric_metadata",
            "categorical_metadata",
        }
        if set(diagnostics) - allowed:
            raise ValueError("Unknown reference/current diagnostic settings")
        input_cfg = section(config, "input")
        reference = _input_path(
            config,
            str(required(diagnostics, "reference_path", section_name="diagnostics")),
        )
        prepared_reference = None
        if config.raw.get("evaluation_design") is not None:
            prepared_reference, record = _prepare_design_audit(
                config, reference, reference_cohort=True
            )
            config = replace(config, design_audits=(*config.design_audits, record))
        primary = section(config, "evaluation").get("primary_metric") or (
            config.protocol.as_dict()["primary_metric"] if config.protocol else None
        )
        shift = diagnose_shift(
            reference,
            _input_path(config, str(input_cfg["path"])),
            target=input_cfg["target_column"],
            prediction_column=input_cfg.get("prediction_column"),
            prediction_columns=input_cfg.get("prediction_columns"),
            task_type=input_cfg.get("task_type"),
            class_labels=input_cfg.get("class_labels"),
            sample_id_column=input_cfg.get("sample_id_column", "sample_id"),
            slice_columns=input_cfg.get("slice_columns", []),
            min_slice_size=input_cfg.get("min_slice_size", 5),
            metric=primary,
            uncertainty_config=_uncertainty_config(config),
            sampling_design=config.raw.get("sampling_design"),
            current_frame=config.prepared_input,
            reference_frame=prepared_reference.frame if prepared_reference else None,
            metric_names=_selected_metric_names(config),
            evaluation_group=_evaluation_group(config),
            **{
                key: value
                for key, value in diagnostics.items()
                if key != "reference_path"
            },
        )
        report_path = Path(summary["json_report"])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["result"]["degradation_summary"] = shift["degradation_summary"]
        report.setdefault("extra", {})["diagnostics_local"] = shift["local"]
        report = attach_integrity_metadata(
            report, signing_secret=_signing_secret(config)
        )
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        summary["degradation_summary"] = shift["degradation_summary"]
        _attach_report_identity(summary, report_path, {})
        if summary.get("markdown_report"):
            with Path(summary["markdown_report"]).open("a", encoding="utf-8") as handle:
                handle.write("\n" + render_degradation(shift["degradation_summary"]))
    if config.design_audits:
        _attach_design_audits(config, summary)
    if "quality_gate" in config.raw:
        from privatelabbench.quality import evaluate_quality_gate
        from privatelabbench.reports.integrity import attach_integrity_metadata

        report_path = Path(summary["json_report"])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        gate = evaluate_quality_gate(report, config.raw["quality_gate"])
        report["result"]["quality_gate"] = gate
        report = attach_integrity_metadata(
            report, signing_secret=_signing_secret(config)
        )
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        summary["quality_gate"] = gate
        _attach_report_identity(summary, report_path, {})
        if summary.get("markdown_report"):
            markdown = Path(summary["markdown_report"])
            counts = {
                status: sum(rule["status"] == status for rule in gate["rules"])
                for status in ("pass", "fail", "investigate")
            }
            with markdown.open("a", encoding="utf-8") as handle:
                handle.write(
                    f"\n## Model-quality gate\n\nStatus: `{gate['status']}`; metric basis: `{gate['metric_basis']}`.\n\n"
                )
                handle.write(
                    "; ".join(f"{status}: {count}" for status, count in counts.items())
                    + ".\n"
                )
    summary["task"] = config.task_id
    summary["workflow"] = config.workflow
    summary["audit_log"] = _write_audit(config, summary)
    manifest_path = write_run_manifest(
        _manifest_path(config),
        summary=summary,
        config_path=config.config_path or config_path,
        json_report_path=summary["json_report"],
        markdown_report_path=summary.get("markdown_report"),
        audit_log_path=summary["audit_log"],
        signing_secret=_signing_secret(config),
    )
    summary["manifest"] = str(manifest_path)
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


def print_run_summary(summary: dict[str, Any]) -> None:
    print("PrivateLabBench local evaluation")
    if "evaluation_protocol" in summary:
        protocol = summary["evaluation_protocol"]
        print(
            f"Protocol: {protocol['id']}@{protocol['version']} (sha256:{protocol['sha256']})"
        )
    if "quality_gate" in summary:
        print(f"Quality gate: {summary['quality_gate']['status']}")
    print(f"Project: {summary['project']}")
    print(f"Task: {summary.get('task', summary.get('workflow'))}")
    if "benchmark_id" in summary:
        print(
            f"Benchmark: {summary['benchmark_id']}@{summary.get('benchmark_version', 'local')}"
        )
    if "run_id" in summary:
        print(f"Run ID: {summary['run_id']}")
    if "task_type" in summary:
        print(f"Problem type: {summary['task_type']}")
    if "n_samples" in summary:
        print(f"Samples: {summary['n_samples']}")
    if "sample_id_status" in summary:
        print(f"Sample IDs: {summary['sample_id_status']}")
    if summary.get("slice_columns"):
        print(f"Slices: {', '.join(summary['slice_columns'])}")
    if "n_clients" in summary:
        print(f"Clients: {summary['n_clients']}")
        print(f"Total samples: {summary['total_samples']}")
    if "clean_metrics" in summary:
        print(f"Clean metrics: {summarize_metrics(summary['clean_metrics'])}")
    if "reported_metrics" in summary:
        print(f"Reported metrics: {summarize_metrics(summary['reported_metrics'])}")
    uncertainty = summary.get("uncertainty")
    if isinstance(uncertainty, dict) and uncertainty.get("status"):
        print(
            "Uncertainty: "
            f"{uncertainty.get('method')} at {float(uncertainty.get('confidence_level', 0.0)):.0%} confidence "
            f"({uncertainty.get('status')})"
        )
    if "aggregate_clean_metrics" in summary:
        print(
            f"Aggregate clean metrics: {summarize_metrics(summary['aggregate_clean_metrics'])}"
        )
    if "aggregate_reported_metrics" in summary:
        print(
            f"Aggregate reported metrics: {summarize_metrics(summary['aggregate_reported_metrics'])}"
        )
    if "privacy_risk_level" in summary:
        print(
            "Privacy attack risk: "
            f"{summary['privacy_risk_level']} "
            f"(member advantage: {float(summary.get('privacy_member_advantage', 0.0)):.4f})"
        )
    if "privacy_gate_status" in summary:
        print(
            "Privacy gate: "
            f"{summary['privacy_gate_status']} "
            f"(shareable: {str(summary.get('privacy_gate_publishable')).lower()})"
        )
    if "aggregate_release_status" in summary:
        print(
            "Aggregate release: "
            f"{summary['aggregate_release_status']} "
            f"(shareable: {str(summary.get('aggregate_release_publishable')).lower()})"
        )
    print(f"Privacy: {summary['privacy']}")
    print(f"Markdown report saved to: {Path(summary['markdown_report'])}")
    print(f"JSON report saved to: {Path(summary['json_report'])}")
    print(f"Audit log saved to: {Path(summary['audit_log'])}")
    print(f"Manifest saved to: {Path(summary['manifest'])}")
