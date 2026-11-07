from copy import deepcopy

import pytest

from scripts.check_release_ci import REQUIRED, verify

SHA = "a" * 40


class API:
    def __init__(self):
        self.runs, self.jobs = {}, {}
        for index, (workflow, names) in enumerate(REQUIRED.items(), 1):
            self.runs[workflow] = [
                {
                    "id": index,
                    "run_number": index,
                    "run_attempt": 1,
                    "head_sha": SHA,
                    "head_branch": "main",
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                }
            ]
            self.jobs[index] = [
                {"name": name, "status": "completed", "conclusion": "success"}
                for name in names
            ]

    def pages(self, path, key):
        if key == "workflow_runs":
            return self.runs[path.split("/workflows/")[1].split("/")[0]]
        return self.jobs[int(path.split("/runs/")[1].split("/")[0])]


def test_green_exact_commit_main_push_runs_are_required():
    result = verify("example/repository", SHA, API())
    assert {row["workflow"] for row in result} == set(REQUIRED)
    assert all(row["sha"] == SHA and row["jobs_passed"] for row in result)


@pytest.mark.parametrize(
    "field,value",
    [
        ("head_sha", "b" * 40),
        ("head_branch", "codex/fix"),
        ("event", "pull_request"),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("conclusion", "cancelled"),
    ],
)
def test_unchecked_or_nonpassing_release_commits_are_blocked(field, value):
    api = API()
    api.runs["ci.yml"][0][field] = value
    with pytest.raises(ValueError):
        verify("example/repository", SHA, api)


@pytest.mark.parametrize("conclusion", ["failure", "skipped", "cancelled", None])
def test_all_required_workflow_jobs_must_pass(conclusion):
    api = API()
    api.jobs[1][0]["conclusion"] = conclusion
    with pytest.raises(ValueError, match="pending, failed, or skipped"):
        verify("example/repository", SHA, api)


def test_missing_jobs_and_missing_workflows_cannot_pass_vacuously():
    api = API()
    api.jobs[1] = []
    with pytest.raises(ValueError, match="missing"):
        verify("example/repository", SHA, api)
    api = API()
    api.runs["ci.yml"] = []
    with pytest.raises(ValueError, match="No main-branch"):
        verify("example/repository", SHA, api)


def test_newer_failed_run_blocks_an_older_success():
    api = API()
    newer = deepcopy(api.runs["ci.yml"][0])
    newer.update(id=100, run_number=100, conclusion="failure")
    api.runs["ci.yml"].append(newer)
    with pytest.raises(ValueError, match="Latest"):
        verify("example/repository", SHA, api)


@pytest.mark.parametrize(
    "repository,sha",
    [("../bad", SHA), ("owner/repo", "main"), ("owner/repo", SHA[:39])],
)
def test_release_identity_is_validated_before_network_access(repository, sha):
    with pytest.raises(ValueError):
        verify(repository, sha, API())
