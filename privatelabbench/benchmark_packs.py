from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from privatelabbench.config import load_config, section
from privatelabbench.core.registry import discover_entrypoint_tasks, get_task
from privatelabbench.runner import ensure_builtin_tasks_registered


PACK_SCHEMA_VERSION = "benchmark-pack/v1"
DEFAULT_PACK_ROOT = Path(__file__).resolve().parent / "data" / "benchmark_packs"


@dataclass(frozen=True)
class BenchmarkPack:
    id: str
    version: str
    task: str
    domain: str
    description: str
    license: str
    root: Path
    config_path: Path
    predictions_path: Path
    expected_receipt_path: Path
    provenance: dict[str, Any]

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": PACK_SCHEMA_VERSION,
            "id": self.id,
            "version": self.version,
            "ref": self.ref,
            "task": self.task,
            "domain": self.domain,
            "description": self.description,
            "license": self.license,
            "config": str(self.config_path),
            "predictions": str(self.predictions_path),
            "expected_receipt": str(self.expected_receipt_path),
            "provenance": dict(self.provenance),
        }


def _required(payload: dict[str, Any], key: str, *, path: Path) -> Any:
    value = payload.get(key)
    if value in (None, ""):
        raise ValueError(f"{path} is missing required benchmark-pack field: {key}")
    return value


def _pack_file(root: Path, files: dict[str, Any], key: str) -> Path:
    value = _required(files, key, path=root / "pack.yaml")
    path = root / str(value)
    if not path.exists() or not path.is_file():
        raise ValueError(f"benchmark-pack file '{key}' does not exist: {path}")
    return path


def load_benchmark_pack(path: str | Path) -> BenchmarkPack:
    root = Path(path)
    manifest_path = root / "pack.yaml" if root.is_dir() else root
    if not manifest_path.exists():
        raise FileNotFoundError(f"benchmark pack manifest does not exist: {manifest_path}")
    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"benchmark pack manifest must be a YAML mapping: {manifest_path}")
    if payload.get("schema_version") != PACK_SCHEMA_VERSION:
        raise ValueError(f"unsupported benchmark pack schema {payload.get('schema_version')!r}; expected {PACK_SCHEMA_VERSION}")

    pack_root = manifest_path.parent
    files = payload.get("files")
    if not isinstance(files, dict):
        raise ValueError(f"{manifest_path} field 'files' must be a mapping")
    provenance = payload.get("provenance", {})
    if not isinstance(provenance, dict):
        raise ValueError(f"{manifest_path} field 'provenance' must be a mapping")

    pack = BenchmarkPack(
        id=str(_required(payload, "id", path=manifest_path)),
        version=str(_required(payload, "version", path=manifest_path)),
        task=str(_required(payload, "task", path=manifest_path)),
        domain=str(_required(payload, "domain", path=manifest_path)),
        description=str(_required(payload, "description", path=manifest_path)),
        license=str(_required(payload, "license", path=manifest_path)),
        root=pack_root,
        config_path=_pack_file(pack_root, files, "config"),
        predictions_path=_pack_file(pack_root, files, "predictions"),
        expected_receipt_path=_pack_file(pack_root, files, "expected_receipt"),
        provenance=dict(provenance),
    )
    validate_benchmark_pack(pack)
    return pack


def validate_benchmark_pack(pack: BenchmarkPack) -> None:
    if not pack.id.strip() or "@" in pack.id:
        raise ValueError("benchmark pack id must be non-empty and must not contain '@'")
    if not pack.version.strip():
        raise ValueError("benchmark pack version must not be empty")
    if not pack.license.strip():
        raise ValueError("benchmark pack must declare a license")
    if not pack.provenance.get("type"):
        raise ValueError("benchmark pack provenance.type is required")

    ensure_builtin_tasks_registered()
    discover_entrypoint_tasks()
    get_task(pack.task)

    config = load_config(str(pack.config_path))
    if config.task_id != pack.task:
        raise ValueError(f"pack task '{pack.task}' does not match config task '{config.task_id}'")
    benchmark = section(config, "benchmark")
    if str(benchmark.get("id", "")) != pack.id:
        raise ValueError("pack id must match config benchmark.id")
    if str(benchmark.get("version", "")) != pack.version:
        raise ValueError("pack version must match config benchmark.version")
    if str(benchmark.get("domain", "")) != pack.domain:
        raise ValueError("pack domain must match config benchmark.domain")

    input_cfg = section(config, "input")
    configured_input = input_cfg.get("path")
    if configured_input is None:
        raise ValueError("benchmark pack config must define input.path")
    configured_path = (pack.config_path.parent / str(configured_input)).resolve()
    if configured_path != pack.predictions_path.resolve():
        raise ValueError("pack files.predictions must match the config input.path")


def discover_benchmark_packs(root: str | Path | None = None) -> tuple[BenchmarkPack, ...]:
    pack_root = Path(root) if root is not None else DEFAULT_PACK_ROOT
    if not pack_root.exists():
        return ()
    packs: list[BenchmarkPack] = []
    seen_refs: set[str] = set()
    for manifest in sorted(pack_root.glob("*/pack.yaml")):
        pack = load_benchmark_pack(manifest)
        if pack.ref in seen_refs:
            raise ValueError(f"duplicate benchmark pack ref: {pack.ref}")
        seen_refs.add(pack.ref)
        packs.append(pack)
    return tuple(packs)


def get_benchmark_pack(ref_or_id: str, root: str | Path | None = None) -> BenchmarkPack:
    query = ref_or_id.strip()
    packs = discover_benchmark_packs(root)
    exact = [pack for pack in packs if pack.ref == query]
    if exact:
        return exact[0]
    by_id = [pack for pack in packs if pack.id == query]
    if len(by_id) == 1:
        return by_id[0]
    if len(by_id) > 1:
        versions = ", ".join(pack.ref for pack in by_id)
        raise ValueError(f"benchmark pack id '{query}' has multiple versions; choose one of: {versions}")
    raise KeyError(f"unknown benchmark pack: {query}")


def run_benchmark_pack(ref_or_id: str, root: str | Path | None = None) -> dict[str, Any]:
    pack = get_benchmark_pack(ref_or_id, root)
    from privatelabbench.runner import run_config

    summary = run_config(str(pack.config_path))
    summary["benchmark_pack"] = pack.ref
    return summary
