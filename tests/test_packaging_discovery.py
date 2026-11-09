"""Package discovery must prune generated trees before inspecting their contents."""

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

import pytest


def test_package_discovery_does_not_traverse_auxiliary_trees(tmp_path, monkeypatch):
    setuptools = pytest.importorskip(
        "setuptools", reason="Packaging backend is not installed"
    )
    from setuptools import discovery

    project = Path(__file__).resolve().parents[1] / "pyproject.toml"
    settings = tomllib.loads(project.read_text(encoding="utf-8"))
    find_settings = settings["tool"]["setuptools"]["packages"]["find"]
    finder = (
        setuptools.find_namespace_packages
        if find_settings.pop("namespaces", True)
        else setuptools.find_packages
    )
    auxiliary = {
        "outputs",
        "reports",
        "build",
        "dist",
        "site",
        "tests",
        "docs",
        "examples",
    }
    for name in auxiliary:
        (tmp_path / name / "nested" / "generated").mkdir(parents=True)
    for relative in ("privatelabbench/core", "privatelabbench/data/schemas"):
        (tmp_path / relative).mkdir(parents=True)
    (tmp_path / "privatelabbench/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "privatelabbench/core/__init__.py").write_text("", encoding="utf-8")

    original_scandir = discovery.os.scandir

    def reject_auxiliary_traversal(path):
        relative = Path(path).resolve().relative_to(tmp_path.resolve())
        assert not relative.parts or relative.parts[0] not in auxiliary, (
            f"Package discovery entered auxiliary tree: {relative}"
        )
        return original_scandir(path)

    with monkeypatch.context() as patch:
        patch.setattr(discovery.os, "scandir", reject_auxiliary_traversal)
        packages = finder(where=str(tmp_path), **find_settings)

    assert set(packages) == {
        "privatelabbench",
        "privatelabbench.core",
        "privatelabbench.data",
        "privatelabbench.data.schemas",
    }
