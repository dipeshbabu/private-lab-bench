import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "audit" / "public_release_manifest.yaml"


def test_history_audit_blocks_unreviewed_email_metadata(monkeypatch):
    from scripts import public_release_audit as audit

    def fake_git(*args):
        if args[0] == "rev-list":
            return "2\n" if "--count" in args else "root\n"
        if "--format=%ae%n%ce" in args:
            return "noreply@github.com\nsynthetic-author@example.invalid\n"
        return ""

    monkeypatch.setattr(audit, "_git", fake_git)
    failures, info = [], {}
    audit.check_git_history(
        {
            "require_reviewed_author_emails": True,
            "allowed_author_emails": ["noreply@github.com"],
        },
        failures,
        info,
    )
    assert failures and info["git_history"]["author_email_privacy_review_required"]
    assert "synthetic-author@example.invalid" not in str(info)


def test_history_audit_respects_explicitly_reviewed_author_exceptions(monkeypatch):
    from scripts import public_release_audit as audit

    def fake_git(*args):
        if args[0] == "rev-list":
            return "1\n" if "--count" in args else "root\n"
        if "--format=%ae%n%ce" in args:
            return "synthetic-author@example.invalid\n"
        return ""

    monkeypatch.setattr(audit, "_git", fake_git)
    failures, info = [], {}
    audit.check_git_history(
        {
            "require_reviewed_author_emails": True,
            "allowed_author_emails": ["synthetic-author@example.invalid"],
        },
        failures,
        info,
    )
    assert failures == []
    assert info["git_history"]["non_noreply_email_count"] == 0


def _dep_name(spec: str) -> str:
    return re.split(r"[<>=!~;\[]", spec, maxsplit=1)[0].strip()


def test_public_release_manifest_covers_all_example_csvs():
    payload = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "public-release-audit/v1"
    declared = {entry["path"] for entry in payload["examples"]}
    actual = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "examples").rglob("*.csv")
        if path.is_file()
    }
    assert declared == actual
    assert all(entry["provenance"] == "synthetic" for entry in payload["examples"])
    assert all(entry["license"] == "CC0-1.0" for entry in payload["examples"])


def test_direct_runtime_dependencies_have_compatible_license_review():
    payload = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]
    dependencies = {_dep_name(spec) for spec in project["dependencies"]}
    reviewed = payload["direct_dependencies"]
    assert set(reviewed) == dependencies
    for name in dependencies:
        assert reviewed[name]["compatible_with_mit_project"] is True
        assert reviewed[name]["license"]
        assert reviewed[name]["source"].startswith("https://github.com/")


def test_bundled_pack_provenance_is_synthetic_and_cc0():
    root = ROOT / "privatelabbench" / "data" / "benchmark_packs"
    manifests = sorted(root.glob("*/pack.yaml"))
    assert manifests
    for path in manifests:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert payload["license"] == "CC0-1.0"
        assert payload["provenance"]["type"] == "synthetic"
        assert payload["provenance"]["derived_from"] == "none"


def test_public_release_workflow_uses_full_history_scanners():
    workflow = (ROOT / ".github" / "workflows" / "public-release-audit.yml").read_text(
        encoding="utf-8"
    )
    assert workflow.count("fetch-depth: 0") >= 3
    assert "gitleaks/gitleaks-action@v3" in workflow
    # Accept reviewed patch/minor updates while requiring a pinned scanner release.
    assert re.search(
        r"uses: trufflesecurity/trufflehog@(v3\.\d+\.\d+|[0-9a-f]{40})\s*$",
        workflow,
        re.MULTILINE,
    )
    assert "--results=verified" in workflow
    assert "--results=verified,unknown" not in workflow
    assert "--no-update" not in workflow


def test_example_provenance_and_audit_docs_exist():
    provenance = (ROOT / "examples" / "PROVENANCE.md").read_text(encoding="utf-8")
    audit_doc = (ROOT / "docs" / "public_release_audit.md").read_text(encoding="utf-8")
    assert "CC0-1.0" in provenance
    assert "full-history" in audit_doc.lower()
    assert "rotate/revoke" in audit_doc
    assert "manual privacy review" in audit_doc.lower()
    assert "unverified postgres" in audit_doc.lower()
