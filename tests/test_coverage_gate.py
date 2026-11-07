import json

import pytest

from scripts.check_coverage import combine, enforce


def write_report(path, name, lines, missing, branches, absent):
    path.write_text(
        json.dumps(
            {
                "meta": {"branch_coverage": True},
                "files": {
                    name: {
                        "executed_lines": lines,
                        "missing_lines": missing,
                        "executed_branches": branches,
                        "missing_branches": absent,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_union_combines_platform_paths_instead_of_averaging_percentages(tmp_path):
    a = write_report(
        tmp_path / "a.json", "privatelabbench/example.py", [1], [2], [[1, 2]], [[1, 3]]
    )
    b = write_report(
        tmp_path / "b.json", "privatelabbench\\example.py", [2], [1], [[1, 3]], [[1, 2]]
    )
    result = combine(
        [a, b], minimum_reports=2, expected_files={"privatelabbench/example.py"}
    )
    assert result["statement_percent"] == result["branch_percent"] == 100
    assert result["files"]["privatelabbench/example.py"] == {
        "missing_lines": [],
        "missing_branches": [],
    }
    enforce(result, 100, 100)


def test_missing_report_or_source_cannot_improve_the_gate(tmp_path):
    a = write_report(
        tmp_path / "a.json", "privatelabbench/example.py", [1], [2], [[1, 2]], [[1, 3]]
    )
    with pytest.raises(ValueError, match="missing"):
        combine([a], minimum_reports=2)
    with pytest.raises(ValueError, match="source files"):
        combine([a], minimum_reports=1, expected_files={"privatelabbench/other.py"})
    result = combine([a], minimum_reports=1)
    with pytest.raises(ValueError, match="below floor"):
        enforce(result, 51, 50)
    with pytest.raises(ValueError, match="below floor"):
        enforce(result, 50, 51)


def test_branch_collection_is_mandatory(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(
        json.dumps({"meta": {"branch_coverage": False}, "files": {}}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="branch data"):
        combine([path], minimum_reports=1)
