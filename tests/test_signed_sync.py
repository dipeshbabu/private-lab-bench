import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from privatelabbench.dashboard.schemas import SanitizedEvidencePayload, SanitizedRunPayload
from privatelabbench.signing import (
    RUNNER_PUBLIC_KEYS_ENV,
    SIGNATURE_ALGORITHM,
    payload_sha256,
    verification_result,
)
from privatelabbench.sync import signed_sync_headers


def _keypair() -> tuple[str, str]:
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


def test_signed_sync_headers_verify_with_registered_public_key():
    private_pem, public_pem = _keypair()
    payload = b'{"project":"demo"}'
    headers = signed_sync_headers(payload, runner_id="runner-1", private_key=private_pem)

    result = verification_result(payload=payload, headers=headers, public_keys={"runner-1": public_pem})

    assert headers["X-Runner-Signature-Alg"] == SIGNATURE_ALGORITHM
    assert headers["X-Runner-Payload-SHA256"] == payload_sha256(payload)
    assert result["verified"] is True
    assert result["runner_id"] == "runner-1"


def test_signed_sync_rejects_tampered_payload():
    private_pem, public_pem = _keypair()
    headers = signed_sync_headers(b'{"project":"demo"}', runner_id="runner-1", private_key=private_pem)

    result = verification_result(payload=b'{"project":"tampered"}', headers=headers, public_keys={"runner-1": public_pem})

    assert result["verified"] is False
    assert result["reason"] == "payload_hash_mismatch"


def test_dashboard_rejects_unsigned_sync_when_runner_registry_is_configured(tmp_path, monkeypatch):
    from privatelabbench.dashboard.api import app

    _, public_pem = _keypair()
    monkeypatch.delenv("PRIVATELABBENCH_DASHBOARD_API_KEY", raising=False)
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_DB", str(tmp_path / "dashboard.db"))
    monkeypatch.setenv(RUNNER_PUBLIC_KEYS_ENV, json.dumps({"runner-1": public_pem}))
    payload = SanitizedRunPayload(
        organization_id="org_1",
        project="demo",
        workflow="predictions",
        benchmark_id="bench-v1",
        metrics={"rmse": 0.1},
    )

    response = TestClient(app).post("/v1/runs", content=payload.model_dump_json())

    assert response.status_code == 401
    assert "missing_runner_signature" in response.text


def test_dashboard_stores_verified_runner_signature(tmp_path, monkeypatch):
    from privatelabbench.dashboard.api import app

    private_pem, public_pem = _keypair()
    monkeypatch.delenv("PRIVATELABBENCH_DASHBOARD_API_KEY", raising=False)
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_DB", str(tmp_path / "dashboard.db"))
    monkeypatch.setenv(RUNNER_PUBLIC_KEYS_ENV, json.dumps({"runner-1": public_pem}))
    payload = SanitizedRunPayload(
        organization_id="org_1",
        project="demo",
        workflow="predictions",
        benchmark_id="bench-v1",
        metrics={"rmse": 0.1},
    )
    body = payload.model_dump_json().encode("utf-8")
    headers = {"Content-Type": "application/json"}
    headers.update(signed_sync_headers(body, runner_id="runner-1", private_key=private_pem))

    response = TestClient(app).post("/v1/runs", content=body, headers=headers)

    assert response.status_code == 200
    synced = response.json()
    assert synced["sync_runner_id"] == "runner-1"
    assert synced["signature_verified"] is True
    assert synced["signature_algorithm"] == SIGNATURE_ALGORITHM
    assert synced["signed_payload_sha256"] == payload_sha256(body)


def test_dashboard_stores_verified_evidence_signature(tmp_path, monkeypatch):
    from privatelabbench.dashboard.api import app

    private_pem, public_pem = _keypair()
    monkeypatch.delenv("PRIVATELABBENCH_DASHBOARD_API_KEY", raising=False)
    monkeypatch.setenv("PRIVATELABBENCH_DASHBOARD_DB", str(tmp_path / "dashboard.db"))
    monkeypatch.setenv(RUNNER_PUBLIC_KEYS_ENV, json.dumps({"runner-1": public_pem}))
    payload = SanitizedEvidencePayload(
        organization_id="org_1",
        project="demo",
        claim="Vendor model improves RMSE",
        recommendation="go",
        decision_status="pass",
        decision_metric="rmse",
        direction="lower_is_better",
        minimum_lift=0.1,
        candidate_value=0.2,
        baseline_value=0.4,
    )
    body = payload.model_dump_json().encode("utf-8")
    headers = {"Content-Type": "application/json"}
    headers.update(signed_sync_headers(body, runner_id="runner-1", private_key=private_pem))

    response = TestClient(app).post("/v1/evidence", content=body, headers=headers)

    assert response.status_code == 200
    synced = response.json()
    assert synced["sync_runner_id"] == "runner-1"
    assert synced["signature_verified"] is True
    assert synced["signature_algorithm"] == SIGNATURE_ALGORITHM
    assert synced["signed_payload_sha256"] == payload_sha256(body)
