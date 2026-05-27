from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from privatelabbench.config import RunnerConfig, section


RUNNER_ID_ENV = "PRIVATELABBENCH_RUNNER_ID"
RUNNER_LABEL_ENV = "PRIVATELABBENCH_RUNNER_LABEL"


def _safe_slug(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value.strip())
    return "-".join(part for part in cleaned.split("-") if part)


def benchmark_metadata(config: RunnerConfig) -> dict[str, Any]:
    """Return dashboard-safe benchmark identity metadata from a run config."""

    benchmark = section(config, "benchmark")
    benchmark_id = str(benchmark.get("id") or f"{config.workflow}-{_safe_slug(config.project)}")
    metadata: dict[str, Any] = {
        "benchmark_id": benchmark_id,
        "benchmark_version": str(benchmark.get("version", "local")),
        "benchmark_suite": str(benchmark.get("suite", config.workflow)),
        "domain": str(benchmark.get("domain", "scientific-ai")),
    }
    protocol = benchmark.get("protocol")
    if protocol:
        metadata["benchmark_protocol"] = str(protocol)
    return metadata


def runner_metadata(config: RunnerConfig) -> dict[str, Any]:
    runner_id = os.getenv(RUNNER_ID_ENV)
    if not runner_id:
        base = Path(config.config_path).stem if config.config_path else config.project
        runner_id = f"local-{_safe_slug(base)}"
    metadata = {"runner_id": runner_id}
    runner_label = os.getenv(RUNNER_LABEL_ENV)
    if runner_label:
        metadata["runner_label"] = runner_label
    return metadata
