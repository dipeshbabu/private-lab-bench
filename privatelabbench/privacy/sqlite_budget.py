"""Local, durable sequential-composition accounting shared by threads/processes."""

from __future__ import annotations

import math
import os
import re
import sys
from contextlib import closing
from dataclasses import dataclass, field
from numbers import Real
from pathlib import Path
from uuid import uuid4

from privatelabbench.privacy.formal import PrivacyBudget, PrivacySpend

_META = """CREATE TABLE plb_budget_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    scope_id TEXT NOT NULL,
    epsilon_limit TEXT NOT NULL,
    delta_limit TEXT NOT NULL,
    ledger_id TEXT NOT NULL
)"""
_SPENDS = """CREATE TABLE plb_budget_spends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    epsilon TEXT NOT NULL,
    delta TEXT NOT NULL
)"""


def _label(value, name):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 256
        or "\0" in value
    ):
        raise ValueError(
            f"{name} must be a nonempty public label of at most 256 characters"
        )
    return value


def _number(value, name):
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not math.isfinite(value)
    ):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _connect(path: Path):
    # mode=rw never creates or silently resets a missing ledger. A separate
    # explicit create operation owns initialization of a new, exclusive file.
    sqlite3 = _sqlite()
    options = {"uri": True, "timeout": 30.0, "isolation_level": None}
    if sys.version_info >= (3, 12):
        options["autocommit"] = sqlite3.LEGACY_TRANSACTION_CONTROL
    connection = sqlite3.connect(path.as_uri() + "?mode=rw", **options)
    try:
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA synchronous=EXTRA")
        if connection.execute("PRAGMA synchronous").fetchone()[0] != 3:
            raise ValueError("Privacy ledger requires synchronized commits")
        if sys.platform == "darwin":
            connection.execute("PRAGMA fullfsync=ON")
    except BaseException:
        connection.close()
        raise
    return connection


def _sqlite():
    # Keep ordinary prediction evaluation usable in custom Python builds that
    # omit this optional standard-library extension.
    try:
        import sqlite3
    except ImportError as exc:
        raise ValueError(
            "SQLitePrivacyBudget requires Python's sqlite3 module"
        ) from exc
    return sqlite3


def _metadata(connection):
    if connection.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise ValueError("Unsupported privacy ledger version")
    expected = {"plb_budget_meta": _META, "plb_budget_spends": _SPENDS}
    definitions = connection.execute(
        "SELECT name, type, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    ).fetchall()
    if len(definitions) != len(expected) or any(
        kind != "table"
        or name not in expected
        or not isinstance(sql, str)
        or " ".join(sql.split()) != " ".join(expected[name].split())
        for name, kind, sql in definitions
    ):
        raise ValueError("Invalid privacy ledger schema")
    if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
        raise ValueError("Privacy ledger requires a local rollback journal")
    rows = connection.execute(
        "SELECT id, scope_id, epsilon_limit, delta_limit, ledger_id FROM plb_budget_meta"
    ).fetchall()
    if len(rows) != 1 or rows[0][0] != 1:
        raise ValueError("Invalid privacy ledger metadata")
    return rows[0][1:]


@dataclass(frozen=True)
class SQLitePrivacyBudget:
    """An explicitly created local ledger for one protected population.

    Share the SAME database and public scope/limits across all releases. Protect
    the database directory and its transaction journal. This does not prevent an owner
    from deleting, restoring, cloning or bypassing the ledger, and is not a
    distributed accountant for network filesystems or unrelated applications.
    """

    _path: Path = field(repr=False)
    scope_id: str
    epsilon_limit: float
    delta_limit: float
    _ledger_id: str = field(repr=False)

    def __post_init__(self):
        object.__setattr__(self, "_path", Path(self._path).resolve())
        _label(self.scope_id, "scope_id")
        epsilon = _number(self.epsilon_limit, "epsilon_limit")
        delta = _number(self.delta_limit, "delta_limit")
        PrivacyBudget(epsilon, delta)
        object.__setattr__(self, "epsilon_limit", epsilon)
        object.__setattr__(self, "delta_limit", delta)
        if not isinstance(self._ledger_id, str) or not re.fullmatch(
            r"[a-f0-9]{32}", self._ledger_id
        ):
            raise ValueError("Invalid privacy ledger identity")

    @classmethod
    def create(cls, path, *, scope_id, epsilon_limit, delta_limit=0.0):
        """Create exactly once; existing files are never overwritten or reset."""
        sqlite3 = _sqlite()
        ledger = cls(Path(path), scope_id, epsilon_limit, delta_limit, uuid4().hex)
        descriptor = os.open(ledger._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            with closing(_connect(ledger._path)) as connection:
                if (
                    connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
                    != "delete"
                ):
                    raise ValueError("Privacy ledger requires a local rollback journal")
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(_META)
                    connection.execute(_SPENDS)
                    connection.execute("PRAGMA user_version=1")
                    connection.execute(
                        "INSERT INTO plb_budget_meta VALUES (1, ?, ?, ?, ?)",
                        (
                            scope_id,
                            ledger.epsilon_limit.hex(),
                            ledger.delta_limit.hex(),
                            ledger._ledger_id,
                        ),
                    )
                    connection.execute("COMMIT")
                except BaseException:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except sqlite3.Error as exc:
            raise ValueError("Could not initialize the privacy ledger") from exc
        # A failed initialization intentionally leaves its file for inspection;
        # initialization never deletes an existing file or guesses it is unused.
        return ledger

    @classmethod
    def open(cls, path, *, scope_id, epsilon_limit, delta_limit=0.0):
        """Reopen existing state with the same expected public scope and limits."""
        sqlite3 = _sqlite()
        resolved = Path(path).resolve()
        try:
            with closing(_connect(resolved)) as connection:
                _, _, _, identity = _metadata(connection)
            ledger = cls(resolved, scope_id, epsilon_limit, delta_limit, identity)
            ledger._snapshot()
            return ledger
        except sqlite3.Error as exc:
            raise ValueError("Could not open the existing privacy ledger") from exc

    def _read(self, connection):
        scope, epsilon, delta, identity = _metadata(connection)
        if (scope, epsilon, delta, identity) != (
            self.scope_id,
            self.epsilon_limit.hex(),
            self.delta_limit.hex(),
            self._ledger_id,
        ):
            raise ValueError("Privacy ledger scope, limits or identity differ")
        rows = connection.execute(
            "SELECT id, label, epsilon, delta FROM plb_budget_spends ORDER BY id"
        ).fetchall()
        sequence = connection.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='plb_budget_spends'"
        ).fetchone()
        if (sequence[0] if sequence else 0) != len(rows):
            raise ValueError("Privacy ledger spend sequence is inconsistent")
        spends = []
        for expected, (identifier, label, epsilon, delta) in enumerate(rows, 1):
            if (
                identifier != expected
                or not isinstance(epsilon, str)
                or not isinstance(delta, str)
            ):
                raise ValueError("Privacy ledger spend records are inconsistent")
            _label(label, "query label")
            spends.append(
                PrivacySpend(label, float.fromhex(epsilon), float.fromhex(delta))
            )
        # The authoritative append-only records are summed exactly rather than
        # trusting a cached floating-point total that could silently drift.
        return PrivacyBudget(self.epsilon_limit, self.delta_limit, spends)

    def _snapshot(self):
        sqlite3 = _sqlite()
        try:
            with closing(_connect(self._path)) as connection:
                connection.execute("BEGIN")
                try:
                    return self._read(connection)
                finally:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
        except sqlite3.Error as exc:
            raise ValueError("Privacy ledger storage is unavailable") from exc

    def spend(self, *, label, epsilon, delta=0.0):
        """Atomically validate and commit a charge before a mechanism samples."""
        sqlite3 = _sqlite()
        _label(label, "query label")
        epsilon, delta = _number(epsilon, "epsilon"), _number(delta, "delta")
        try:
            with closing(_connect(self._path)) as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    budget = self._read(connection)
                    budget.spend(label=label, epsilon=epsilon, delta=delta)
                    connection.execute(
                        "INSERT INTO plb_budget_spends (label, epsilon, delta) VALUES (?, ?, ?)",
                        (label, epsilon.hex(), delta.hex()),
                    )
                    connection.execute("COMMIT")
                except BaseException:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
        except sqlite3.Error as exc:
            raise ValueError(
                "Privacy ledger storage is unavailable; no release is permitted"
            ) from exc

    @property
    def spends(self):
        return tuple(self._snapshot().spends)

    @property
    def epsilon_spent(self):
        return self._snapshot().epsilon_spent

    @property
    def delta_spent(self):
        return self._snapshot().delta_spent

    @property
    def epsilon_remaining(self):
        return self._snapshot().epsilon_remaining

    @property
    def delta_remaining(self):
        return self._snapshot().delta_remaining

    def as_dict(self):
        """Local ledger inspection without a filesystem path or private rows."""
        return {
            "storage": "sqlite_rollback",
            "scope_id": self.scope_id,
            **self._snapshot().as_dict(),
        }
