import re
from pathlib import Path

import yaml


def test_privileged_label_workflow_checks_out_only_the_trusted_base():
    root = Path(__file__).resolve().parents[1]
    text = (root / ".github/workflows/labels.yml").read_text(encoding="utf-8")
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    assert "pull_request_target" in workflow["on"]
    assert "pull_request" not in workflow["on"]
    assert workflow["permissions"] == {}
    job = workflow["jobs"]["metadata-labels"]
    assert job["permissions"] == {
        "contents": "read",
        "issues": "write",
        "pull-requests": "read",
    }
    checkout = job["steps"][0]
    assert checkout["with"]["ref"] == "${{ github.event.repository.default_branch }}"
    assert checkout["with"]["persist-credentials"] == "false"
    assert "pull_request.head" not in text and "github.head_ref" not in text
    for step in job["steps"]:
        assert re.fullmatch(r"actions/[a-z-]+@[a-f0-9]{40}", step["uses"])


def test_label_workflow_does_not_interpolate_untrusted_text_into_code():
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.load(
        (root / ".github/workflows/labels.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    steps = workflow["jobs"]["metadata-labels"]["steps"]
    assert all("run" not in step for step in steps)
    script = steps[-1]["with"]["script"]
    assert "${{" not in script
    assert "process.env.GITHUB_WORKSPACE" in script and "auto-label.cjs" in script
