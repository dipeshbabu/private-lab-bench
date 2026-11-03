import json
from pathlib import Path
import subprocess
import sys

import pytest

from privatelabbench import __version__


@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="The release workflow uses Python 3.11 and stdlib tomllib",
)
@pytest.mark.parametrize("citation_matches", [True, False])
def test_release_guard_checks_citation_version(tmp_path, citation_matches):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / "privatelabbench").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nversion = "{__version__}"\n', encoding="utf-8"
    )
    (tmp_path / "privatelabbench/__init__.py").write_text(
        f'__version__ = "{__version__}"\n', encoding="utf-8"
    )
    parts = __version__.split(".")
    changed = ".".join([*parts[:-1], str(int(parts[-1]) + 1)])
    citation = __version__ if citation_matches else changed
    (tmp_path / "CITATION.cff").write_text(
        f'cff-version: 1.2.0\nversion: "{citation}"\n', encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, str(root / "scripts/check_release_version.py"), __version__],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is citation_matches
    if not citation_matches:
        assert (
            "release version mismatch" in result.stderr
            and f"citation={changed}" in result.stderr
        )


def test_reference_artifacts_identify_the_current_package_release():
    root = Path(__file__).resolve().parents[1]
    fixtures = [
        root / "examples/reports/evaluation_receipt_example.json",
        *sorted(
            (root / "privatelabbench/data/benchmark_packs").glob(
                "*/expected_receipt.json"
            )
        ),
    ]
    for path in fixtures:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        assert artifact["shareable"]["provenance"]["package"]["version"] == __version__
    approved = root / "examples/caco2_case/approved"
    for name in (
        "reference-candidate",
        "proxy-candidate",
        "proxy-baseline",
        "proxy-paired",
    ):
        artifact = json.loads((approved / f"{name}.json").read_text(encoding="utf-8"))
        assert (
            artifact["signer_statement"]["evaluation_code"]["package_version"]
            == __version__
        )
