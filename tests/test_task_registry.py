from __future__ import annotations

from pathlib import Path

import pytest

from privatelabbench.config import load_config
from privatelabbench.core.registry import get_task, has_task, register_task
from privatelabbench.runner import ensure_builtin_tasks_registered, run_config


def test_builtin_tasks_are_registered() -> None:
    ensure_builtin_tasks_registered()
    assert has_task("predictions")
    assert has_task("tabular")
    assert has_task("molecules")
    assert has_task("multi-site")


def test_duplicate_task_ids_are_rejected() -> None:
    task_id = "test-duplicate-task"
    def runner(config):
        return {"project": config.project}
    if not has_task(task_id):
        register_task(task_id, runner)
    with pytest.raises(ValueError, match="already registered"):
        register_task(task_id, runner)


def test_custom_task_can_be_registered_and_resolved() -> None:
    task_id = "test-custom-task"
    def runner(config):
        return {"project": config.project, "json_report": "", "markdown_report": ""}
    if not has_task(task_id):
        register_task(task_id, runner, description="test task")
    spec = get_task(task_id)
    assert spec.id == task_id
    assert spec.description == "test task"


def test_task_key_is_preferred_but_workflow_remains_compatible(tmp_path: Path) -> None:
    config_path = tmp_path / "task.yaml"
    config_path.write_text(
        """
project: task-alias
task: tabular
input:
  path: examples/tabular_predictions_demo.csv
  target_column: target
  prediction_column: prediction
  task_type: regression
privacy:
  mode: none
""".strip(),
        encoding="utf-8",
    )
    config = load_config(str(config_path))
    assert config.task_id == "tabular"
    assert config.workflow == "tabular"


def test_non_molecular_tabular_task_runs(tmp_path: Path) -> None:
    config_path = tmp_path / "tabular.yaml"
    md_path = tmp_path / "tabular.md"
    json_path = tmp_path / "tabular.json"
    manifest_path = tmp_path / "tabular_manifest.json"
    audit_path = tmp_path / "tabular_audit.jsonl"
    config_path.write_text(
        f"""
project: tabular-test
task: tabular
input:
  path: examples/tabular_predictions_demo.csv
  target_column: target
  prediction_column: prediction
  task_type: regression
privacy:
  mode: none
report:
  markdown: {md_path}
  json: {json_path}
  manifest: {manifest_path}
audit:
  path: {audit_path}
""".strip(),
        encoding="utf-8",
    )
    summary = run_config(str(config_path))
    assert summary["task"] == "tabular"
    assert summary["n_samples"] == 8
    assert md_path.exists()
    assert json_path.exists()
    assert manifest_path.exists()
    assert audit_path.exists()
