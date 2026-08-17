from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_required_community_files_exist():
    required = [
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "SECURITY.md",
        "GOVERNANCE.md",
        "CITATION.cff",
        ".github/pull_request_template.md",
        ".github/ISSUE_TEMPLATE/bug.yml",
        ".github/ISSUE_TEMPLATE/feature.yml",
        ".github/ISSUE_TEMPLATE/task_or_benchmark.yml",
        ".github/ISSUE_TEMPLATE/privacy_method.yml",
        ".github/ISSUE_TEMPLATE/config.yml",
    ]
    for relative in required:
        assert (ROOT / relative).is_file(), relative


def test_citation_metadata_is_parseable_and_points_to_repository():
    payload = yaml.safe_load((ROOT / "CITATION.cff").read_text(encoding="utf-8"))
    assert payload["cff-version"] == "1.2.0"
    assert payload["title"] == "PrivateLabBench"
    assert payload["license"] == "MIT"
    assert payload["repository-code"] == "https://github.com/dipeshbabu/private-lab-bench"
    assert payload["authors"][0]["family-names"] == "Mahato"


def test_issue_templates_are_structured_and_nonempty():
    template_dir = ROOT / ".github" / "ISSUE_TEMPLATE"
    for path in sorted(template_dir.glob("*.yml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if path.name == "config.yml":
            assert payload["blank_issues_enabled"] is False
            continue
        assert payload["name"]
        assert payload["description"]
        assert isinstance(payload["body"], list) and payload["body"]


def test_contributor_docs_cover_extension_and_privacy_paths():
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "privatelabbench.tasks" in contributing
    assert "benchmark pack" in contributing.lower()
    assert "privacy audit" in contributing.lower()
    assert "Artifact/schema changes" in contributing

    privacy_template = (ROOT / ".github" / "ISSUE_TEMPLATE" / "privacy_method.yml").read_text(encoding="utf-8")
    assert "Threat model" in privacy_template
    assert "guarantee" in privacy_template.lower()


def test_security_policy_warns_against_public_vulnerability_details():
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "Do not open a public GitHub issue" in security
    assert "synthetic" in security.lower()
