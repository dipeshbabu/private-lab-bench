"""Fail closed unless the exact release commit passed the required main workflows."""

from __future__ import annotations

import argparse
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PLATFORMS = [
    ("ubuntu-latest", version) for version in ("3.10", "3.11", "3.12", "3.13", "3.14")
] + [
    (os_name, version)
    for os_name in ("windows-latest", "macos-latest")
    for version in ("3.12", "3.14")
]
REQUIRED = {
    "ci.yml": {
        "package",
        "code-quality",
        "sandbox-runtime",
        "onboarding-pypi",
        "coverage-gate",
    }
    | {f"test ({system}, {version})" for system, version in PLATFORMS},
    "compatibility.yml": {"build-core-distributions"}
    | {f"installed-core ({system}, {version})" for system, version in PLATFORMS},
    "public-release-audit.yml": {
        "repository-policy",
        "gitleaks-history",
        "trufflehog-history",
    },
}


class GitHub:
    def __init__(self, token):
        if not token:
            raise ValueError(
                "GH_TOKEN or GITHUB_TOKEN is required for release verification"
            )
        self.token = token

    def pages(self, path, key):
        rows = []
        for page in range(1, 11):
            separator = "&" if "?" in path else "?"
            request = Request(
                "https://api.github.com"
                + path
                + separator
                + urlencode({"per_page": 100, "page": page}),
                headers={
                    "Authorization": "Bearer " + self.token,
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            with urlopen(request, timeout=30) as response:
                content = response.read(5_000_001)
            if len(content) > 5_000_000:
                raise ValueError("GitHub verification response exceeds its size limit")
            value = json.loads(content)
            batch = value.get(key) if isinstance(value, dict) else None
            if not isinstance(batch, list):
                raise ValueError("GitHub verification response has an invalid shape")
            rows.extend(batch)
            if len(batch) < 100:
                return rows
        raise ValueError("GitHub verification requires too many pages")


def verify(repository, sha, api):
    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+", repository
    ) or repository.split("/")[-1] in {".", ".."}:
        raise ValueError("Expected an owner/repository name")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected the full release commit SHA")
    checked = []
    for workflow, required_names in REQUIRED.items():
        path = f"/repos/{repository}/actions/workflows/{workflow}/runs?" + urlencode(
            {"head_sha": sha, "branch": "main", "event": "push"}
        )
        candidates = [
            run
            for run in api.pages(path, "workflow_runs")
            if run.get("head_sha") == sha
            and run.get("head_branch") == "main"
            and run.get("event") == "push"
        ]
        if not candidates:
            raise ValueError(
                f"No main-branch push run for {workflow} at the release SHA"
            )
        latest = max(
            candidates,
            key=lambda run: (
                run.get("run_number", 0),
                run.get("run_attempt", 0),
                run.get("id", 0),
            ),
        )
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            raise ValueError(f"Latest {workflow} run has not passed at the release SHA")
        jobs = api.pages(
            f"/repos/{repository}/actions/runs/{latest['id']}/jobs?filter=latest",
            "jobs",
        )
        if not required_names <= {job.get("name") for job in jobs}:
            raise ValueError(f"Required jobs are missing from {workflow}")
        if any(
            job.get("status") != "completed" or job.get("conclusion") != "success"
            for job in jobs
        ):
            raise ValueError(f"A job in {workflow} is pending, failed, or skipped")
        checked.append(
            {
                "workflow": workflow,
                "run_id": latest["id"],
                "sha": sha,
                "jobs_passed": len(jobs),
            }
        )
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    try:
        checked = verify(
            args.repository,
            args.sha,
            GitHub(os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")),
        )
    except (ValueError, KeyError, TypeError, HTTPError, URLError, OSError) as exc:
        parser.exit(1, f"Release blocked: {exc}\n")
    print(json.dumps(checked, indent=2))


if __name__ == "__main__":
    main()
