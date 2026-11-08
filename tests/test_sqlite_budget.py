import json
import multiprocessing
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from privatelabbench.privacy import SQLitePrivacyBudget


def _open(path, **changes):
    return SQLitePrivacyBudget.open(
        path, scope_id="public-study", epsilon_limit=0.75, **changes
    )


def _contender(path, ready, start, results):
    try:
        budget = _open(path)
        ready.put(True)
        if not start.wait(90):
            raise RuntimeError("Start checkpoint timed out")
        try:
            budget.spend(label="parallel-query", epsilon=0.25)
            results.put("charged")
        except ValueError as exc:
            results.put(
                "exceeded"
                if "budget exceeded" in str(exc)
                else "unexpected: " + str(exc)
            )
    except BaseException as exc:
        results.put("unexpected: " + type(exc).__name__ + ": " + str(exc))


def _crash_before_commit(path):

    original = sqlite3.connect

    class CrashConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == "COMMIT":
                os._exit(23)
            return super().execute(sql, *args, **kwargs)

    def connect(*args, **kwargs):
        return original(*args, factory=CrashConnection, **kwargs)

    sqlite3.connect = connect
    _open(path).spend(label="never-returned", epsilon=0.5)


def _exit_after_charge(path):
    _open(path).spend(label="charged-before-exit", epsilon=0.5)
    os._exit(24)


def test_reopening_keeps_exact_composition_and_cannot_raise_the_limit(tmp_path):
    path = tmp_path / "budget 測試.db"
    budget = SQLitePrivacyBudget.create(
        path, scope_id="public-study", epsilon_limit=0.75
    )
    budget.spend(label="one", epsilon=0.5)
    reopened = _open(path)
    assert reopened.epsilon_spent == 0.5 and reopened.epsilon_remaining == 0.25
    reopened.spend(label="two", epsilon=0.25)
    assert budget.epsilon_spent == 0.75 and len(budget.spends) == 2
    with pytest.raises(ValueError, match="exceeded"):
        _open(path).spend(label="overflow", epsilon=0.25)
    for scope, limit in [("different-study", 0.75), ("public-study", 1.0)]:
        with pytest.raises(ValueError, match="differ"):
            SQLitePrivacyBudget.open(path, scope_id=scope, epsilon_limit=limit)
    assert str(path) not in json.dumps(budget.as_dict())


def test_create_does_not_overwrite_a_database_or_an_unrelated_input(tmp_path):
    path = tmp_path / "input.csv"
    original = b"private-input-must-survive\n"
    path.write_bytes(original)
    with pytest.raises(FileExistsError):
        SQLitePrivacyBudget.create(path, scope_id="public-study", epsilon_limit=0.75)
    assert path.read_bytes() == original
    with pytest.raises(ValueError):
        _open(path)
    assert path.read_bytes() == original
    missing = tmp_path / "missing.db"
    with pytest.raises(ValueError):
        _open(missing)
    assert not missing.exists()


def test_missing_sqlite_extension_fails_only_when_a_durable_ledger_is_requested(
    tmp_path, monkeypatch
):
    import sys

    path = tmp_path / "unavailable.db"
    monkeypatch.setitem(sys.modules, "sqlite3", None)
    with pytest.raises(ValueError, match="sqlite3 module"):
        SQLitePrivacyBudget.create(path, scope_id="public-study", epsilon_limit=0.75)
    assert not path.exists()


@pytest.mark.parametrize("spend", [float("nan"), float("inf"), 0.0, -1.0, True])
def test_invalid_spends_are_not_committed(tmp_path, spend):
    path = tmp_path / "budget.db"
    budget = SQLitePrivacyBudget.create(
        path, scope_id="public-study", epsilon_limit=0.75
    )
    with pytest.raises(ValueError):
        budget.spend(label="invalid", epsilon=spend)
    assert _open(path).epsilon_spent == 0.0


def test_binary_float_budget_boundary_is_not_rounded_down(tmp_path):
    path = tmp_path / "boundary.db"
    budget = SQLitePrivacyBudget.create(path, scope_id="boundary", epsilon_limit=0.3)
    budget.spend(label="first", epsilon=0.1)
    with pytest.raises(ValueError, match="exceeded"):
        budget.spend(label="second", epsilon=0.2)
    assert len(budget.spends) == 1 and budget.epsilon_remaining < 0.2


def test_delta_composition_and_parameterized_labels_remain_valid(tmp_path):
    path = tmp_path / "approximate.db"
    budget = SQLitePrivacyBudget.create(
        path, scope_id="public-study", epsilon_limit=1.0, delta_limit=0.25
    )
    budget.spend(
        label="query'); DROP TABLE plb_budget_spends; --", epsilon=0.5, delta=0.125
    )
    budget.spend(
        label="query'); DROP TABLE plb_budget_spends; --", epsilon=0.5, delta=0.125
    )
    assert budget.delta_spent == 0.25 and budget.delta_remaining == 0.0
    assert budget.epsilon_spent == 1.0 and len(budget.spends) == 2


def test_threads_cannot_spend_from_stale_snapshots(tmp_path):
    path = tmp_path / "threads.db"
    budget = SQLitePrivacyBudget.create(
        path, scope_id="public-study", epsilon_limit=0.75
    )

    def charge(_):
        try:
            _open(path).spend(label="thread", epsilon=0.25)
            return True
        except ValueError as exc:
            assert "budget exceeded" in str(exc)
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(charge, range(4)))
    assert sum(results) == 3 and budget.epsilon_spent == 0.75


def test_processes_share_one_atomic_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    path = tmp_path / "processes.db"
    budget = SQLitePrivacyBudget.create(
        path, scope_id="public-study", epsilon_limit=0.75
    )
    context = multiprocessing.get_context("spawn")
    ready, results, start = context.Queue(), context.Queue(), context.Event()
    workers = [
        context.Process(target=_contender, args=(path, ready, start, results))
        for _ in range(4)
    ]
    for worker in workers:
        worker.start()
    try:
        assert all(ready.get(timeout=120) for _ in workers)
        start.set()
        outcomes = [results.get(timeout=120) for _ in workers]
        assert sorted(outcomes) == ["charged"] * 3 + ["exceeded"]
    finally:
        start.set()
        for worker in workers:
            worker.join(120)
            if worker.is_alive():
                worker.terminate()
                worker.join()
        ready.close()
        results.close()
        ready.join_thread()
        results.join_thread()
    assert all(worker.exitcode == 0 for worker in workers)
    assert budget.epsilon_spent == 0.75 and len(budget.spends) == 3


@pytest.mark.parametrize(
    "target,exit_code,expected",
    [(_crash_before_commit, 23, 0.0), (_exit_after_charge, 24, 0.5)],
)
def test_process_exit_does_not_create_partial_or_forgotten_charges(
    tmp_path, monkeypatch, target, exit_code, expected
):
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    path = tmp_path / "crash.db"
    SQLitePrivacyBudget.create(path, scope_id="public-study", epsilon_limit=0.75)
    worker = multiprocessing.get_context("spawn").Process(target=target, args=(path,))
    worker.start()
    worker.join(120)
    if worker.is_alive():
        worker.terminate()
        worker.join()
    assert worker.exitcode == exit_code
    budget = _open(path)
    assert budget.epsilon_spent == expected
    budget.spend(label="after-restart", epsilon=0.25)
    assert budget.epsilon_spent == expected + 0.25


@pytest.mark.parametrize(
    "mutation", ["missing_record", "nan_spend", "foreign_schema", "changed_identity"]
)
def test_corrupt_or_replaced_state_never_grants_a_release(tmp_path, mutation):
    path = tmp_path / "corrupt.db"
    budget = SQLitePrivacyBudget.create(
        path, scope_id="public-study", epsilon_limit=0.75
    )
    budget.spend(label="one", epsilon=0.25)
    with sqlite3.connect(path) as connection:
        if mutation == "missing_record":
            connection.execute("DELETE FROM plb_budget_spends")
        elif mutation == "nan_spend":
            connection.execute("UPDATE plb_budget_spends SET epsilon='nan'")
        elif mutation == "foreign_schema":
            connection.execute("CREATE TABLE unrelated (value TEXT)")
        else:
            connection.execute("UPDATE plb_budget_meta SET ledger_id=?", ("a" * 32,))
    with pytest.raises(ValueError):
        budget.spend(label="must-not-release", epsilon=0.25)
