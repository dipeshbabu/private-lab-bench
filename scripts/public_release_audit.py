from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "audit" / "public_release_manifest.yaml"


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _dependency_name(spec: str) -> str:
    return re.split(r"[<>=!~;\[]", spec, maxsplit=1)[0].strip()


def _email_allowed(email: str, *, exact: set[str], suffixes: tuple[str, ...]) -> bool:
    normalized = email.strip().lower()
    if not normalized:
        return False
    if normalized in exact:
        return True
    return any(normalized.endswith(suffix.lower()) for suffix in suffixes)


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"audit manifest must be a YAML mapping: {path}")
    if payload.get("schema_version") != "public-release-audit/v1":
        raise ValueError("unsupported public-release audit manifest schema")
    return payload


def check_current_tree(payload: dict[str, Any], failures: list[str], info: dict[str, Any]) -> None:
    tracked = {line.strip() for line in _git("ls-files").splitlines() if line.strip()}
    forbidden_hits: list[str] = []
    for forbidden in payload.get("forbidden_current_paths", []):
        normalized = str(forbidden).rstrip("/")
        if normalized in tracked or any(path.startswith(normalized + "/") for path in tracked):
            forbidden_hits.append(normalized)
    if forbidden_hits:
        failures.append("forbidden current-tree commercial/service paths remain")
    info["current_tree"] = {
        "tracked_files": len(tracked),
        "forbidden_path_hits": forbidden_hits,
    }


def check_examples(payload: dict[str, Any], failures: list[str], info: dict[str, Any]) -> None:
    declared = {
        str(item["path"]): {"provenance": str(item.get("provenance", "")), "license": str(item.get("license", ""))}
        for item in payload.get("examples", [])
        if isinstance(item, dict) and item.get("path")
    }
    actual = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "examples").rglob("*.csv")
        if path.is_file()
    }
    missing_declarations = sorted(actual - set(declared))
    stale_declarations = sorted(set(declared) - actual)
    bad_declarations = sorted(
        path
        for path, metadata in declared.items()
        if metadata["provenance"] != "synthetic" or metadata["license"] != "CC0-1.0"
    )
    if missing_declarations:
        failures.append("tracked example CSVs are missing provenance declarations")
    if stale_declarations:
        failures.append("example provenance manifest contains missing files")
    if bad_declarations:
        failures.append("example CSV provenance/license is not synthetic + CC0-1.0")

    pack_errors: list[str] = []
    pack_count = 0
    pack_root = ROOT / "privatelabbench" / "data" / "benchmark_packs"
    for manifest in sorted(pack_root.glob("*/pack.yaml")):
        pack_count += 1
        pack = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        provenance = pack.get("provenance", {}) if isinstance(pack, dict) else {}
        if not isinstance(pack, dict) or pack.get("license") != "CC0-1.0":
            pack_errors.append(manifest.relative_to(ROOT).as_posix() + ":license")
        if not isinstance(provenance, dict) or provenance.get("type") != "synthetic" or provenance.get("derived_from") != "none":
            pack_errors.append(manifest.relative_to(ROOT).as_posix() + ":provenance")
    if pack_errors:
        failures.append("benchmark-pack provenance/license checks failed")

    info["examples"] = {
        "declared_csvs": len(declared),
        "actual_csvs": len(actual),
        "missing_declarations": missing_declarations,
        "stale_declarations": stale_declarations,
        "invalid_declarations": bad_declarations,
        "benchmark_pack_count": pack_count,
        "benchmark_pack_errors": pack_errors,
    }


def check_direct_dependencies(payload: dict[str, Any], failures: list[str], info: dict[str, Any]) -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    dependencies = {_dependency_name(spec) for spec in project.get("dependencies", [])}
    reviewed = payload.get("direct_dependencies", {})
    if not isinstance(reviewed, dict):
        failures.append("direct_dependencies audit manifest section is invalid")
        reviewed = {}
    reviewed_names = set(reviewed)
    missing = sorted(dependencies - reviewed_names)
    stale = sorted(reviewed_names - dependencies)
    incompatible = sorted(
        name
        for name in dependencies & reviewed_names
        if not bool(reviewed.get(name, {}).get("compatible_with_mit_project"))
        or not str(reviewed.get(name, {}).get("license", "")).strip()
        or not str(reviewed.get(name, {}).get("source", "")).startswith("https://")
    )
    if missing:
        failures.append("direct dependencies are missing license review entries")
    if incompatible:
        failures.append("direct dependency license review has unresolved/incompatible entries")
    info["direct_dependencies"] = {
        "project_dependencies": sorted(dependencies),
        "reviewed_dependencies": sorted(reviewed_names),
        "missing_review": missing,
        "stale_review": stale,
        "unresolved_or_incompatible": incompatible,
    }


def check_git_history(payload: dict[str, Any], failures: list[str], info: dict[str, Any]) -> None:
    commit_count = int(_git("rev-list", "--all", "--count").strip())
    root_commits = [line for line in _git("rev-list", "--max-parents=0", "--all").splitlines() if line.strip()]

    exact = {str(value).lower() for value in payload.get("allowed_author_emails", [])}
    suffixes = tuple(str(value).lower() for value in payload.get("allowed_author_email_suffixes", []))
    raw_emails = _git("log", "--all", "--format=%ae%n%ce").splitlines()
    unique_emails = sorted({email.strip() for email in raw_emails if email.strip()})
    exposed = [email for email in unique_emails if not _email_allowed(email, exact=exact, suffixes=suffixes)]
    if exposed:
        failures.append("git history contains non-noreply author/committer email addresses; history privacy review/rewrite required")

    all_paths = sorted({line.strip() for line in _git("log", "--all", "--name-only", "--pretty=format:").splitlines() if line.strip()})
    sensitive_matches: dict[str, list[str]] = {}
    for pattern in payload.get("historical_sensitive_path_patterns", []):
        regex = re.compile(str(pattern), re.IGNORECASE)
        matches = [path for path in all_paths if regex.search(path)]
        if matches:
            sensitive_matches[str(pattern)] = matches

    info["git_history"] = {
        "commit_count": commit_count,
        "root_commit_count": len(root_commits),
        "unique_author_committer_emails": len(unique_emails),
        "non_noreply_email_count": len(exposed),
        "non_noreply_email_fingerprints": [_fingerprint(email) for email in exposed],
        "history_rewrite_required_for_email_privacy": bool(exposed),
        "historical_sensitive_path_inventory": sensitive_matches,
    }


def run_audit(manifest_path: Path = DEFAULT_MANIFEST) -> tuple[dict[str, Any], list[str]]:
    payload = load_manifest(manifest_path)
    failures: list[str] = []
    info: dict[str, Any] = {
        "schema_version": "public-release-audit-result/v1",
        "manifest": manifest_path.relative_to(ROOT).as_posix(),
    }
    check_current_tree(payload, failures, info)
    check_examples(payload, failures, info)
    check_direct_dependencies(payload, failures, info)
    check_git_history(payload, failures, info)
    info["status"] = "pass" if not failures else "fail"
    info["failures"] = failures
    return info, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic PrivateLabBench public-release repository checks.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()

    result, failures = run_audit(args.manifest)
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    if failures:
        print("Public-release audit failed. See failure categories above; secret values are intentionally never printed.", file=sys.stderr)
        return 1
    print("Public-release deterministic audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
