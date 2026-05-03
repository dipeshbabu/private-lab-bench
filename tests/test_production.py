from __future__ import annotations

from argparse import Namespace

import pytest

from privatelabbench import api
from privatelabbench.cli import serve_api, serve_dashboard_api
from privatelabbench.production import validate_runtime


def test_production_api_requires_key_and_run_root(monkeypatch):
    monkeypatch.setenv("PRIVATELABBENCH_ENV", "production")
    monkeypatch.delenv("PRIVATELABBENCH_API_KEY", raising=False)
    monkeypatch.delenv("PRIVATELABBENCH_RUN_ROOT", raising=False)

    errors = validate_runtime("api")

    assert "Missing required production environment variable: PRIVATELABBENCH_API_KEY" in errors
    assert "Missing required production environment variable: PRIVATELABBENCH_RUN_ROOT" in errors


def test_production_dashboard_requires_key_and_database(monkeypatch):
    monkeypatch.setenv("PRIVATELABBENCH_ENV", "production")
    monkeypatch.delenv("PRIVATELABBENCH_DASHBOARD_API_KEY", raising=False)
    monkeypatch.delenv("PRIVATELABBENCH_DASHBOARD_DB", raising=False)

    errors = validate_runtime("dashboard")

    assert "Missing required production environment variable: PRIVATELABBENCH_DASHBOARD_API_KEY" in errors
    assert "Missing required production environment variable: PRIVATELABBENCH_DASHBOARD_DB" in errors


def test_production_dashboard_validates_database_parent_not_database_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("PRIVATELABBENCH_ENV", "production")
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_API_KEY", "secret")
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_DB", str(tmp_path / "nested" / "dashboard"))

    errors = validate_runtime("dashboard")

    assert errors == []
    assert (tmp_path / "nested").is_dir()
    assert not (tmp_path / "nested" / "dashboard").exists()


def test_production_api_validates_run_root_as_directory(tmp_path, monkeypatch):
    run_root = tmp_path / "nested" / "runs"
    monkeypatch.setenv("PRIVATELABBENCH_ENV", "production")
    monkeypatch.setenv("PRIVATELABBENCH_API_KEY", "secret")
    monkeypatch.setenv("PRIVATELABBENCH_RUN_ROOT", str(run_root))

    errors = validate_runtime("api")

    assert errors == []
    assert run_root.is_dir()


def test_production_rejects_placeholder_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("PRIVATELABBENCH_ENV", "production")
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_API_KEY", "change-me-dashboard-secret")
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_DB", str(tmp_path / "dashboard.db"))

    errors = validate_runtime("dashboard")

    assert "Production environment variable is still a placeholder: PRIVATELABBENCH_DASHBOARD_API_KEY" in errors


def test_serve_api_fails_before_startup_when_production_config_is_invalid(monkeypatch):
    monkeypatch.setenv("PRIVATELABBENCH_ENV", "production")
    monkeypatch.delenv("PRIVATELABBENCH_API_KEY", raising=False)
    monkeypatch.delenv("PRIVATELABBENCH_RUN_ROOT", raising=False)

    with pytest.raises(SystemExit) as exc:
        serve_api(Namespace(host="127.0.0.1", port=8000, reload=False))

    assert "PrivateLabBench production configuration is invalid" in str(exc.value)
    assert "PRIVATELABBENCH_API_KEY" in str(exc.value)


def test_serve_dashboard_fails_before_startup_when_production_config_is_invalid(monkeypatch):
    monkeypatch.setenv("PRIVATELABBENCH_ENV", "production")
    monkeypatch.delenv("PRIVATELABBENCH_DASHBOARD_API_KEY", raising=False)
    monkeypatch.delenv("PRIVATELABBENCH_DASHBOARD_DB", raising=False)

    with pytest.raises(SystemExit) as exc:
        serve_dashboard_api(Namespace(host="127.0.0.1", port=8010, reload=False))

    assert "PrivateLabBench production configuration is invalid" in str(exc.value)
    assert "PRIVATELABBENCH_DASHBOARD_API_KEY" in str(exc.value)


def test_api_run_root_reads_environment_at_runtime(tmp_path, monkeypatch):
    run_root = tmp_path / "runs"
    monkeypatch.setenv("PRIVATELABBENCH_RUN_ROOT", str(run_root))

    assert api._run_root() == run_root
    assert run_root.exists()
