from __future__ import annotations

import argparse

from privatelabbench.cli import build_parser


def _command_names(parser: argparse.ArgumentParser) -> set[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("CLI parser does not define subcommands")


def test_cli_parser_contains_community_core_commands() -> None:
    parser = build_parser()
    commands = _command_names(parser)
    assert {
        "run",
        "validate-config",
        "list-tasks",
        "compare",
        "eval-predictions",
        "eval-molecules",
        "eval-federated",
        "verify-report",
        "verify-manifest",
    }.issubset(commands)
    removed_product_commands = {
        "serve",
        "serve-dashboard",
        "sync-dashboard",
        "sync-evidence",
        "backup-dashboard",
        "restore-dashboard",
        "prune-dashboard-audit",
        "evidence",
    }
    assert commands.isdisjoint(removed_product_commands)


def test_package_imports() -> None:
    import privatelabbench
    assert privatelabbench is not None
