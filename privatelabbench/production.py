from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path


ENVIRONMENT_ENV = "PRIVATELABBENCH_ENV"
API_KEY_ENV = "PRIVATELABBENCH_API_KEY"
DASHBOARD_API_KEY_ENV = "PRIVATELABBENCH_DASHBOARD_API_KEY"
DASHBOARD_API_KEYS_ENV = "PRIVATELABBENCH_DASHBOARD_API_KEYS"
DASHBOARD_DB_ENV = "PRIVATELABBENCH_DASHBOARD_DB"
DASHBOARD_DATABASE_URL_ENV = "PRIVATELABBENCH_DASHBOARD_DATABASE_URL"
DASHBOARD_RATE_LIMIT_ENV = "PRIVATELABBENCH_DASHBOARD_RATE_LIMIT_PER_MINUTE"
AUDIT_RETENTION_DAYS_ENV = "PRIVATELABBENCH_AUDIT_RETENTION_DAYS"
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


def _validate_dashboard_keys() -> list[str]:
    global_key = os.getenv(DASHBOARD_API_KEY_ENV, "").strip()
    org_keys_raw = os.getenv(DASHBOARD_API_KEYS_ENV, "").strip()
    if not global_key and not org_keys_raw:
        return [
            f"Missing required production environment variable: {DASHBOARD_API_KEY_ENV} or {DASHBOARD_API_KEYS_ENV}"
        ]

    errors: list[str] = []
    if global_key and global_key.lower().startswith(PLACEHOLDER_PREFIXES):
        errors.append(f"Production environment variable is still a placeholder: {DASHBOARD_API_KEY_ENV}")
    if org_keys_raw:
        try:
            org_keys = json.loads(org_keys_raw)
            if not isinstance(org_keys, dict):
                errors.append(f"{DASHBOARD_API_KEYS_ENV} must be a JSON object mapping organization id to API key.")
            elif not org_keys and not global_key:
                errors.append(f"{DASHBOARD_API_KEYS_ENV} must contain at least one organization API key.")
            else:
                for org_id, api_key in org_keys.items():
                    if not str(org_id).strip() or not str(api_key).strip():
                        errors.append(f"{DASHBOARD_API_KEYS_ENV} contains an empty organization id or API key.")
                    elif str(api_key).strip().lower().startswith(PLACEHOLDER_PREFIXES):
                        errors.append(f"{DASHBOARD_API_KEYS_ENV} contains a placeholder API key for organization: {org_id}")
        except json.JSONDecodeError as exc:
            errors.append(f"{DASHBOARD_API_KEYS_ENV} must be valid JSON: {exc}")
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


def _validate_positive_int_env(name: str, *, allow_zero: bool = False) -> list[str]:
    value = os.getenv(name, "").strip()
    if not value:
        return []
    try:
        parsed = int(value)
    except ValueError:
        return [f"{name} must be an integer."]
    minimum = 0 if allow_zero else 1
    if parsed < minimum:
        return [f"{name} must be at least {minimum}."]
    return []


def _validate_dashboard_storage() -> list[str]:
    database_url = os.getenv(DASHBOARD_DATABASE_URL_ENV, "").strip()
    dashboard_db = os.getenv(DASHBOARD_DB_ENV, "").strip()
    if database_url:
        if not database_url.startswith(("postgres://", "postgresql://")):
            return [f"{DASHBOARD_DATABASE_URL_ENV} must start with postgresql:// or postgres://."]
        if importlib.util.find_spec("psycopg") is None:
            return [
                f"{DASHBOARD_DATABASE_URL_ENV} requires psycopg. Install with: pip install -e '.[postgres]'"
            ]
        return []
    if not dashboard_db:
        return [
            f"Missing required production environment variable: {DASHBOARD_DB_ENV} or {DASHBOARD_DATABASE_URL_ENV}"
        ]
    return _validate_writable_path(dashboard_db, label=DASHBOARD_DB_ENV, directory=False)


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
        errors.extend(_validate_dashboard_keys())
        errors.extend(_validate_dashboard_storage())
        errors.extend(_validate_positive_int_env(DASHBOARD_RATE_LIMIT_ENV, allow_zero=True))
        errors.extend(_validate_positive_int_env(AUDIT_RETENTION_DAYS_ENV))
    else:
        errors.append(f"Unknown production service: {service}")
    return errors


def assert_runtime(service: str) -> None:
    errors = validate_runtime(service)
    if errors:
        details = "\n".join(f"- {error}" for error in errors)
        raise SystemExit(f"PrivateLabBench production configuration is invalid:\n{details}")
