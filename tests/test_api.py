from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from privatelabbench import api
from privatelabbench.api import app


def test_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_run_with_inline_prediction_config(tmp_path: Path, monkeypatch) -> None:
    run_root = tmp_path / "runs"
    monkeypatch.setattr(api, "DEFAULT_RUN_ROOT", run_root)
    monkeypatch.delenv("PRIVATELABBENCH_API_KEY", raising=False)

    data_path = tmp_path / "predictions.csv"
    data_path.write_text("label,pred\n0.1,0.1\n0.2,0.25\n0.3,0.28\n0.4,0.39\n", encoding="utf-8")

    report_dir = tmp_path / "reports"
    config = {
        "project": "api-test",
        "workflow": "predictions",
        "input": {
            "path": str(data_path),
            "target_column": "label",
            "prediction_column": "pred",
            "task_type": "regression",
        },
        "privacy": {"mode": "none", "seed": 13},
        "report": {
            "markdown": str(report_dir / "api_test.md"),
            "json": str(report_dir / "api_test.json"),
        },
        "audit": {"path": str(report_dir / "audit.jsonl")},
    }

    client = TestClient(app)
    response = client.post("/v1/runs", json={"run_id": "api-test-run", "config": config})
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == "api-test-run"
    assert payload["status"] == "completed"
    assert payload["summary"]["workflow"] == "predictions"
    assert Path(payload["summary"]["json_report"]).exists()

    get_response = client.get("/v1/runs/api-test-run")
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "completed"

    record_path = run_root / "api-test-run.json"
    assert record_path.exists()
    assert json.loads(record_path.read_text(encoding="utf-8"))["status"] == "completed"


def test_api_key_is_enforced(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(api, "DEFAULT_RUN_ROOT", tmp_path / "runs")
    monkeypatch.setenv("PRIVATELABBENCH_API_KEY", "secret")
    client = TestClient(app)

    response = client.get("/v1/runs/missing")
    assert response.status_code == 401

    response = client.get("/v1/runs/missing", headers={"x-api-key": "secret"})
    assert response.status_code == 404
