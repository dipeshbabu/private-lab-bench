from __future__ import annotations

import argparse

from privatelabbench.cli import build_parser


def _command_names(parser: argparse.ArgumentParser) -> set[str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("CLI parser does not define subcommands")


def test_cli_parser_contains_product_commands() -> None:
    parser = build_parser()
    commands = _command_names(parser)
    assert {"run", "compare", "eval-predictions", "eval-molecules", "eval-federated", "verify-report"}.issubset(commands)


def test_package_imports() -> None:
    import privatelabbench

    assert privatelabbench is not None
