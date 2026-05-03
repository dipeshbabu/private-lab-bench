from __future__ import annotations

import os
from pathlib import Path


ENVIRONMENT_ENV = "PRIVATELABBENCH_ENV"
API_KEY_ENV = "PRIVATELABBENCH_API_KEY"
DASHBOARD_API_KEY_ENV = "PRIVATELABBENCH_DASHBOARD_API_KEY"
DASHBOARD_DB_ENV = "PRIVATELABBENCH_DASHBOARD_DB"
RUN_ROOT_ENV = "PRIVATELABBENCH_RUN_ROOT"

PRODUCTION_VALUES = {"prod", "production"}
PLACEHOLDER_PREFIXES = ("change-me", "replace-me", "replace-with")


def is_production() -> bool:
    return os.getenv(ENVIRONMENT_ENV, "").strip().lower() in PRODUCTION_VALUES


def _missing_env(names: list[str]) -> list[str]:
    return [name for name in names if not os.getenv(name, "").strip()]


def _placeholder_env(names: list[str]) -> list[str]:
    placeholders: list[str] = []
    for name in names:
        value = os.getenv(name, "").strip().lower()
        if value.startswith(PLACEHOLDER_PREFIXES):
            placeholders.append(name)
    return placeholders


def _validate_required_env(names: list[str]) -> list[str]:
    errors = [f"Missing required production environment variable: {name}" for name in _missing_env(names)]
    errors.extend(f"Production environment variable is still a placeholder: {name}" for name in _placeholder_env(names))
    return errors


def _validate_writable_path(path_value: str, *, label: str, directory: bool) -> list[str]:
    errors: list[str] = []
    path = Path(path_value)
    parent = path if directory else path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return [f"{label} parent cannot be created: {parent} ({exc})"]
    if not parent.is_dir():
        errors.append(f"{label} parent is not a directory: {parent}")
    elif not os.access(parent, os.W_OK):
        errors.append(f"{label} parent is not writable: {parent}")
    return errors


def validate_runtime(service: str) -> list[str]:
    if not is_production():
        return []

    errors: list[str] = []
    if service == "api":
        errors.extend(_validate_required_env([API_KEY_ENV, RUN_ROOT_ENV]))
        run_root = os.getenv(RUN_ROOT_ENV)
        if run_root:
            errors.extend(_validate_writable_path(run_root, label=RUN_ROOT_ENV, directory=True))
    elif service == "dashboard":
        errors.extend(_validate_required_env([DASHBOARD_API_KEY_ENV, DASHBOARD_DB_ENV]))
        dashboard_db = os.getenv(DASHBOARD_DB_ENV)
        if dashboard_db:
            errors.extend(_validate_writable_path(dashboard_db, label=DASHBOARD_DB_ENV, directory=False))
    else:
        errors.append(f"Unknown production service: {service}")
    return errors


def assert_runtime(service: str) -> None:
    errors = validate_runtime(service)
    if errors:
        details = "\n".join(f"- {error}" for error in errors)
        raise SystemExit(f"PrivateLabBench production configuration is invalid:\n{details}")
