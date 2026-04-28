from __future__ import annotations

from privatelabbench.cli import build_parser


def test_cli_parser_contains_product_commands() -> None:
    parser = build_parser()
    commands = parser._subparsers._actions[-1].choices  # argparse public API is limited here.
    assert "eval-predictions" in commands
    assert "eval-molecules" in commands
    assert "verify-report" in commands


def test_package_imports() -> None:
    import privatelabbench

    assert privatelabbench is not None
