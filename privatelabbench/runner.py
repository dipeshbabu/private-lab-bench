from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from privatelabbench.adapters.sklearn_adapter import build_molecule_adapter
from privatelabbench.audit import write_audit_event
from privatelabbench.config import RunnerConfig, load_config, required, section
from privatelabbench.eval.metrics import summarize_metrics
from privatelabbench.eval.predictions import evaluate_prediction_csv
from privatelabbench.federated.evaluator import evaluate_federated_directory
from privatelabbench.identity import benchmark_metadata, runner_metadata
from privatelabbench.privacy.dp import PrivacyConfig, privatize_metrics, privacy_summary
from privatelabbench.reports.json import write_json_report
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
        epsilon=float(privacy.get("epsilon", 8.0)),
        sensitivity=float(privacy.get("sensitivity", 1.0)),
        seed=int(privacy.get("seed", 13)),
    )


def _report_path(config: RunnerConfig, key: str, default: str) -> str:
    report = section(config, "report")
    return str(report.get(key, default))


def _input_path(config: RunnerConfig, value: str) -> str:
    candidate = Path(value)
    if candidate.is_absolute():
        return str(candidate)
    cwd_relative = Path.cwd() / candidate
    if cwd_relative.exists():
        return str(cwd_relative)
    if config.config_path:
        return str(Path(config.config_path).parent / candidate)
    return str(candidate)


def _signing_secret(config: RunnerConfig) -> str | None:
    report = section(config, "report")
    secret = report.get("signing_secret") or os.getenv("PRIVATELABBENCH_SIGNING_SECRET")
    return str(secret) if secret else None


def _audit_path(config: RunnerConfig) -> str:
    audit = section(config, "audit")
    return str(audit.get("path", f"reports/{config.project}_audit.jsonl"))


def _write_audit(config: RunnerConfig, summary: dict[str, Any]) -> str:
    audit_path = _audit_path(config)
    write_audit_event(
        audit_path,
        event_type="evaluation_completed",
        payload={
            "project": config.project,
            "workflow": config.workflow,
            "markdown_report": summary.get("markdown_report"),
            "json_report": summary.get("json_report"),
            "privacy": summary.get("privacy"),
        },
    )
    return audit_path


def _identity_metadata(config: RunnerConfig) -> dict[str, Any]:
    return {**benchmark_metadata(config), **runner_metadata(config)}


def _attach_report_identity(summary: dict[str, Any], json_path: Path, identity: dict[str, Any]) -> dict[str, Any]:
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
    prediction_column = str(required(input_cfg, "prediction_column", section_name="input"))
    task_type = input_cfg.get("task_type")
    split_column = input_cfg.get("split_column")
    privacy_config = _privacy_config(config)
    identity = _identity_metadata(config)

    result = evaluate_prediction_csv(
        path,
        target=target,
        prediction_column=prediction_column,
        task_type=task_type,
        split_column=str(split_column) if split_column else None,
    )
    clean_metrics = result.metrics
    reported_metrics = privatize_metrics(clean_metrics, privacy_config)

    json_path = write_json_report(
        _report_path(config, "json", f"reports/{config.project}_prediction_eval.json"),
        report_type="prediction_evaluation",
        result={
            "project": config.project,
            "dataset_path": result.dataset_path,
            "target_column": result.target_column,
            "prediction_column": result.prediction_column,
            "task_type": result.task_type,
            "n_samples": result.n_samples,
            "clean_metrics": clean_metrics,
            "reported_metrics": reported_metrics,
            "prediction_summary": result.prediction_summary,
            "split_column": result.split_column,
            "privacy_risk": result.privacy_risk or {},
        },
        privacy_config=privacy_config,
        extra=identity,
        config_snapshot=config.raw,
        signing_secret=_signing_secret(config),
    )
    markdown_path = write_prediction_markdown_report(
        _report_path(config, "markdown", f"reports/{config.project}_prediction_eval.md"),
        result=result,
        clean_metrics=clean_metrics,
        private_metrics=reported_metrics,
        privacy_config=privacy_config,
        json_report_path=str(json_path),
    )
    summary = {
        "project": config.project,
        "workflow": config.workflow,
        "task_type": result.task_type,
        "n_samples": result.n_samples,
        "clean_metrics": clean_metrics,
        "reported_metrics": reported_metrics,
        "markdown_report": str(markdown_path),
        "json_report": str(json_path),
        "privacy": privacy_summary(privacy_config),
    }
    if result.privacy_risk:
        summary["privacy_risk_level"] = result.privacy_risk.get("risk_level")
        summary["privacy_attack_auc"] = result.privacy_risk.get("attack_auc")
        summary["privacy_member_advantage"] = result.privacy_risk.get("member_advantage")
        summary["split_column"] = result.split_column
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

    dataset = load_molecule_csv(path, target=target, smiles_column=smiles_column, task_type=task_type)
    adapter = build_molecule_adapter(model_cfg)
    result = adapter.evaluate(dataset, test_size=test_size, seed=seed)
    clean_metrics = dict(result["metrics"])
    reported_metrics = privatize_metrics(clean_metrics, privacy_config)

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
        },
        privacy_config=privacy_config,
        extra=identity,
        config_snapshot=config.raw,
        signing_secret=_signing_secret(config),
    )
    summary = {
        "project": config.project,
        "workflow": config.workflow,
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
    return _attach_report_identity(summary, json_path, identity)


def run_federated_workflow(config: RunnerConfig) -> dict[str, Any]:
    input_cfg = section(config, "input")
    client_dir = _input_path(config, str(required(input_cfg, "client_dir", section_name="input")))
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
        },
        privacy_config=privacy_config,
        extra=identity,
        config_snapshot=config.raw,
        signing_secret=_signing_secret(config),
    )
    summary = {
        "project": config.project,
        "workflow": config.workflow,
        "n_clients": result["n_clients"],
        "total_samples": result["total_samples"],
        "aggregate_clean_metrics": result["aggregate_clean_metrics"],
        "aggregate_reported_metrics": result["aggregate_reported_metrics"],
        "markdown_report": str(markdown_path),
        "json_report": str(json_path),
        "privacy": privacy_summary(privacy_config),
    }
    return _attach_report_identity(summary, json_path, identity)


def run_config(config_path: str) -> dict[str, Any]:
    config = load_config(config_path)
    if config.workflow == "predictions":
        summary = run_prediction_workflow(config)
    elif config.workflow == "molecules":
        summary = run_molecule_workflow(config)
    elif config.workflow == "federated":
        summary = run_federated_workflow(config)
    else:
        raise ValueError(f"Unsupported workflow: {config.workflow}")
    summary["audit_log"] = _write_audit(config, summary)
    return summary


def print_run_summary(summary: dict[str, Any]) -> None:
    print("PrivateLabBench config runner")
    print(f"Project: {summary['project']}")
    print(f"Workflow: {summary['workflow']}")
    if "benchmark_id" in summary:
        print(f"Benchmark: {summary['benchmark_id']}@{summary.get('benchmark_version', 'local')}")
    if "run_id" in summary:
        print(f"Run ID: {summary['run_id']}")
    if "task_type" in summary:
        print(f"Task: {summary['task_type']}")
    if "n_samples" in summary:
        print(f"Samples: {summary['n_samples']}")
    if "n_clients" in summary:
        print(f"Clients: {summary['n_clients']}")
        print(f"Total samples: {summary['total_samples']}")
    if "clean_metrics" in summary:
        print(f"Clean metrics: {summarize_metrics(summary['clean_metrics'])}")
    if "reported_metrics" in summary:
        print(f"Reported metrics: {summarize_metrics(summary['reported_metrics'])}")
    if "aggregate_clean_metrics" in summary:
        print(f"Aggregate clean metrics: {summarize_metrics(summary['aggregate_clean_metrics'])}")
    if "aggregate_reported_metrics" in summary:
        print(f"Aggregate reported metrics: {summarize_metrics(summary['aggregate_reported_metrics'])}")
    if "privacy_risk_level" in summary:
        print(
            "Privacy attack risk: "
            f"{summary['privacy_risk_level']} "
            f"(member advantage: {float(summary.get('privacy_member_advantage', 0.0)):.4f})"
        )
    print(f"Privacy: {summary['privacy']}")
    print(f"Markdown report saved to: {Path(summary['markdown_report'])}")
    print(f"JSON report saved to: {Path(summary['json_report'])}")
    print(f"Audit log saved to: {Path(summary['audit_log'])}")
