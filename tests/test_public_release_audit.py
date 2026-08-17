from pathlib import Path
import re
import tomllib

import yaml


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "audit" / "public_release_manifest.yaml"


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
    workflow = (ROOT / ".github" / "workflows" / "public-release-audit.yml").read_text(encoding="utf-8")
    assert workflow.count("fetch-depth: 0") >= 3
    assert "gitleaks/gitleaks-action@v3" in workflow
    assert "trufflesecurity/trufflehog@v3.93.4" in workflow
    assert "--results=verified,unknown" in workflow


def test_example_provenance_and_audit_docs_exist():
    provenance = (ROOT / "examples" / "PROVENANCE.md").read_text(encoding="utf-8")
    audit_doc = (ROOT / "docs" / "public_release_audit.md").read_text(encoding="utf-8")
    assert "CC0-1.0" in provenance
    assert "full repository history" in audit_doc.lower()
    assert "rotate/revoke" in audit_doc
