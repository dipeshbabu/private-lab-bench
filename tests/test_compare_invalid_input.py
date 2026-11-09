"""Expected comparison input errors stop at the CLI boundary before report writes."""

import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from privatelabbench import cli

ROOT = Path(__file__).resolve().parents[1]


def _write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample_id", "target", "prediction"])
        writer.writerows(rows)


def _inputs(tmp_path, case):
    rows = [[f"s{i}", i % 2, 0.9 if i % 2 else 0.1] for i in range(8)]
    first, second = tmp_path / "a.csv", tmp_path / "b.csv"
    _write(first, rows)
    other = [row.copy() for row in rows]
    if case == "missing_row":
        other.pop()
    elif case == "duplicate_id":
        other.append(other[0].copy())
    elif case == "target_mismatch":
        other[0][1] = 1 - other[0][1]
    elif case == "missing_file":
        return first, second
    elif case == "inferred_bad_candidate_id":
        _write(first, rows + [rows[0].copy()])
    elif case == "reordered":
        other.reverse()
    else:
        raise AssertionError(case)
    _write(second, other)
    return first, second


def _run(first, second, report, markdown, *, infer=False):
    args = [
        sys.executable,
        "-m",
        "privatelabbench.cli",
        "compare",
        str(first),
        str(second),
        "--task-type",
        "classification",
        "--class-labels",
        "0",
        "1",
        "--metric",
        "auroc",
        "--resamples",
        "100",
        "--permutations",
        "0",
        "--min-samples",
        "2",
        "--json-report",
        str(report),
        "--report",
        str(markdown),
    ]
    if not infer:
        args.extend(["--target", "target"])
    return subprocess.run(
        args,
        cwd=ROOT,
        env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONNOUSERSITE="1"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize(
    "case",
    [
        "missing_row",
        "duplicate_id",
        "target_mismatch",
        "missing_file",
        "inferred_bad_candidate_id",
    ],
)
@pytest.mark.parametrize("stale", [False, True])
def test_compare_cli_rejects_invalid_inputs_without_writing_reports(
    tmp_path, case, stale
):
    first, second = _inputs(tmp_path, case)
    originals = {path: path.read_bytes() for path in (first, second) if path.exists()}
    report, markdown = tmp_path / "comparison.json", tmp_path / "comparison.md"
    public = tmp_path / "comparison.shareable.json"
    if stale:
        report.write_bytes(b"preserved older local evidence")
        public.write_text("obsolete aggregate", encoding="utf-8")
    result = _run(
        first, second, report, markdown, infer=case == "inferred_bad_candidate_id"
    )
    assert result.returncode == 1
    assert result.stderr == ""
    assert result.stdout.startswith("Comparison rejected: ")
    diagnostic = {
        "missing_row": "exactly the same sample IDs",
        "duplicate_id": "duplicate sample IDs",
        "target_mismatch": "Targets disagree",
        "missing_file": "No such file",
        "inferred_bad_candidate_id": "Stable sample IDs must be unique",
    }[case]
    assert diagnostic in result.stdout
    assert "Traceback" not in result.stdout
    assert not public.exists()
    assert not markdown.exists()
    if stale:
        assert report.read_bytes() == b"preserved older local evidence"
    else:
        assert not report.exists()
    assert all(path.read_bytes() == contents for path, contents in originals.items())


def test_compare_cli_preserves_input_when_report_path_aliases_it(tmp_path):
    first, second = _inputs(tmp_path, "reordered")
    contents = first.read_bytes()
    result = _run(first, second, first, tmp_path / "comparison.md")
    assert result.returncode == 1 and result.stderr == ""
    assert result.stdout.startswith("Comparison rejected: ")
    assert first.read_bytes() == contents


def test_compare_cli_still_aligns_reordered_inputs_and_scores_them(tmp_path):
    first, second = _inputs(tmp_path, "reordered")
    report = tmp_path / "comparison.json"
    result = _run(first, second, report, tmp_path / "comparison.md")
    assert result.returncode == 0 and result.stderr == ""
    payload = json.loads(report.read_text(encoding="utf-8"))["shareable"]
    assert payload["alignment"]["status"] == "exact_sample_id_match"
    assert payload["alignment"]["dropped_samples"] == 0
    assert payload["n_samples"] == 8
    assert payload["model_a"]["selected_metric"] == 1.0
    assert payload["model_b"]["selected_metric"] == 1.0
    assert payload["improvement_a_over_b"] == 0.0


@pytest.mark.parametrize("exception", [TypeError, KeyError, AttributeError])
def test_compare_cli_does_not_swallow_programming_errors(monkeypatch, exception):
    def broken(args):
        raise exception("comparison programming error")

    monkeypatch.setattr(cli, "compare_command", broken)
    monkeypatch.setattr(
        sys, "argv", ["plb", "compare", "a.csv", "b.csv", "--target", "target"]
    )
    with pytest.raises(exception, match="comparison programming error"):
        cli.main()


def test_compare_cli_handles_permission_error(monkeypatch, capsys):
    def denied(args):
        raise PermissionError(13, "Permission denied", "private.csv")

    monkeypatch.setattr(cli, "compare_command", denied)
    monkeypatch.setattr(
        sys, "argv", ["plb", "compare", "a.csv", "b.csv", "--target", "target"]
    )
    assert cli.main() == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.startswith("Comparison rejected: ")
    assert "Permission denied" in captured.out


def test_compare_imports_from_this_worktree():
    assert Path(cli.__file__).resolve() == ROOT / "privatelabbench" / "cli.py"
