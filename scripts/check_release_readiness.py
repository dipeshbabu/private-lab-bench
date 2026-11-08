"""Keep new releases blocked until their recorded prerequisites have evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REQUIREMENTS = frozenset(
    {
        "failure_path_tests",
        "dependency_and_platform_coverage",
        "automated_security_review",
        "independent_privacy_sandbox_audit",
        "durable_privacy_accounting",
        "multifile_cpu_sandbox",
        "expanded_benchmark_parity",
        "gpu_runtime_validation",
    }
)
STATUSES = frozenset({"pending", "in_progress", "unavailable", "complete"})


def _version(value):
    if not isinstance(value, str):
        raise ValueError("Release version must be a string")
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)([a-zA-Z0-9.-]*)", value)
    if match is None:
        raise ValueError("Invalid release version")
    return tuple(int(part) for part in match.groups()[:3]), match[4]


def verify_readiness(version: str, readiness: dict) -> dict:
    """Validate the record and fail closed for any release after its baseline.

    Evidence is a reviewable record, not an automated assertion of a human audit.
    The existing exact-SHA CI gate remains an additional publication requirement.
    """
    candidate, suffix = _version(version)
    if (
        not isinstance(readiness, dict)
        or set(readiness)
        != {"schema_version", "baseline_version", "milestone", "requirements"}
        or readiness["schema_version"] != "release-readiness/v1"
    ):
        raise ValueError("Invalid release-readiness/v1 record")
    baseline, baseline_suffix = _version(readiness["baseline_version"])
    milestone, milestone_suffix = _version(readiness["milestone"])
    if baseline_suffix or milestone_suffix or milestone <= baseline:
        raise ValueError("Readiness milestone must follow its stable baseline")
    requirements = readiness["requirements"]
    if not isinstance(requirements, dict) or set(requirements) != REQUIREMENTS:
        raise ValueError("Readiness record must contain every required prerequisite")
    pending = []
    for name, entry in requirements.items():
        if not isinstance(entry, dict) or set(entry) != {"status", "evidence"}:
            raise ValueError(f"Invalid readiness entry: {name}")
        if entry["status"] not in STATUSES or not isinstance(entry["evidence"], list):
            raise ValueError(f"Invalid readiness status/evidence: {name}")
        if any(
            not isinstance(item, str) or not item.strip() for item in entry["evidence"]
        ):
            raise ValueError(f"Readiness evidence must use nonempty references: {name}")
        if entry["status"] == "complete" and not entry["evidence"]:
            raise ValueError(f"Completed prerequisite needs evidence: {name}")
        if entry["status"] != "complete":
            pending.append(f"{name} ({entry['status']})")
    if candidate < baseline or candidate == baseline and not suffix:
        return {"status": "historical_release", "version": version}
    if pending:
        raise ValueError(
            f"Release hold for {readiness['milestone']} and later: "
            + "; ".join(pending)
        )
    return {"status": "ready", "version": version, "requirements": sorted(requirements)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument(
        "--record",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "audit/release-readiness.json",
    )
    args = parser.parse_args()
    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
        result = verify_readiness(args.version, record)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, f"Release readiness rejected: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
