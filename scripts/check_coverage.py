"""Combine per-job JSON coverage across platforms and enforce separate floors."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def combine(reports, *, minimum_reports, expected_files=None):
    if len(reports) < minimum_reports:
        raise ValueError("Coverage reports are missing")
    files = {}
    for report in reports:
        data = json.loads(Path(report).read_text(encoding="utf-8"))
        if data.get("meta", {}).get("branch_coverage") is not True or not data.get(
            "files"
        ):
            raise ValueError("A coverage report has no branch data or source files")
        names = set()
        for raw_name, record in data["files"].items():
            name = raw_name.replace("\\", "/")
            if not name.startswith("privatelabbench/") or ".." in name.split("/"):
                raise ValueError("Coverage must use repository-relative package paths")
            names.add(name)
            lines, missing = set(record["executed_lines"]), set(record["missing_lines"])
            branches = {tuple(value) for value in record["executed_branches"]}
            absent = {tuple(value) for value in record["missing_branches"]}
            if lines & missing or branches & absent:
                raise ValueError("Coverage report contains conflicting execution data")
            entry = files.setdefault(
                name,
                {
                    "statements": set(),
                    "executed": set(),
                    "branches": set(),
                    "taken": set(),
                },
            )
            entry["statements"].update(lines | missing)
            entry["executed"].update(lines)
            entry["branches"].update(branches | absent)
            entry["taken"].update(branches)
        if expected_files is not None and names != expected_files:
            raise ValueError("Coverage report omits or adds package source files")
    total_lines = sum(len(item["statements"]) for item in files.values())
    total_branches = sum(len(item["branches"]) for item in files.values())
    if not total_lines or not total_branches:
        raise ValueError("Coverage has no executable statements or branches")
    return {
        "reports": len(reports),
        "statement_percent": 100
        * sum(len(item["executed"]) for item in files.values())
        / total_lines,
        "branch_percent": 100
        * sum(len(item["taken"]) for item in files.values())
        / total_branches,
        "files": {
            name: {
                "missing_lines": sorted(item["statements"] - item["executed"]),
                "missing_branches": sorted(item["branches"] - item["taken"]),
            }
            for name, item in sorted(files.items())
        },
    }


def enforce(result, statement_floor, branch_floor):
    if any(
        not math.isfinite(value) or not 0 <= value <= 100
        for value in (statement_floor, branch_floor)
    ):
        raise ValueError("Coverage floors must be finite percentages")
    if (
        result["statement_percent"] < statement_floor
        or result["branch_percent"] < branch_floor
    ):
        raise ValueError(
            f"Coverage below floor: statements={result['statement_percent']:.2f}% (required {statement_floor:g}%), branches={result['branch_percent']:.2f}% (required {branch_floor:g}%)"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--minimum-reports", type=int, default=18)
    parser.add_argument("--statement-floor", type=float, default=85)
    parser.add_argument("--branch-floor", type=float, default=75)
    parser.add_argument("--output", type=Path, default=Path("combined-coverage.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        if args.minimum_reports < 1:
            raise ValueError("At least one coverage report is required")
        expected = {
            path.relative_to(root).as_posix()
            for path in (root / "privatelabbench").rglob("*.py")
        }
        result = combine(
            sorted(args.reports_dir.rglob("coverage.json")),
            minimum_reports=args.minimum_reports,
            expected_files=expected,
        )
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        enforce(result, args.statement_floor, args.branch_floor)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f"Coverage rejected: {exc}\n")
    print(
        f"Combined {result['reports']} reports: statements {result['statement_percent']:.2f}%, branches {result['branch_percent']:.2f}%"
    )


if __name__ == "__main__":
    main()
