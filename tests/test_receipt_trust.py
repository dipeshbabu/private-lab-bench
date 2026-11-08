import base64
import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from privatelabbench.cli import main
from privatelabbench.reports.integrity import (
    attach_integrity_metadata,
    compute_payload_sha256,
)
from privatelabbench.reports.receipt import verify_receipt
from privatelabbench.reports.trust import sign_artifact
from privatelabbench.runner import run_config


def _public(key):
    return base64.b64encode(
        key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()


def _write(path, payload):
    path.write_text(json.dumps(payload))
    return path


@pytest.fixture
def signed(tmp_path):
    key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "lab-private.pem"
    key_path.write_bytes(
        key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    )
    signer = {
        "private_key": str(key_path),
        "signer_id": "lab-a",
        "key_id": "lab-a-2026",
        "protocol": {
            "id": "plb://community/regression",
            "version": "1.0.0",
            "sha256": "a" * 64,
        },
        "model": {"id": "baseline", "revision": "frozen-1"},
    }
    source = json.loads(
        Path("examples/reports/evaluation_receipt_example.json").read_text()
    )
    payload = sign_artifact(source, signer)
    path = _write(tmp_path / "signed.json", payload)
    trust = {
        "schema_version": "receipt-trust-store/v1",
        "keys": {
            "lab-a-2026": {
                "signer_id": "lab-a",
                "public_key": _public(key),
                "revoked": False,
            }
        },
    }
    return path, payload, trust, signer


def test_offline_pinned_signature_authenticates_statement_but_not_execution(signed):
    path, payload, trust, signer = signed
    result = verify_receipt(
        path,
        trust_store=trust,
        require_trusted_signer=True,
        expected_protocol_sha256="a" * 64,
    )
    assert result["valid"] and result["hash_valid"]
    assert (
        result["signature_present"]
        and result["signature_valid"]
        and result["signer_trusted"]
    )
    assert (
        result["protocol_bound"]
        and result["protocol_recognized"]
        and result["model_identity_bound"]
    )
    assert result["evidence_level"] == "authenticated_signer_statement"
    assert result["execution_verified"] is False and result["science_valid"] is None
    assert "PRIVATE KEY" not in json.dumps(payload) and signer[
        "private_key"
    ] not in json.dumps(payload)
    schema = json.loads(
        Path(
            "privatelabbench/data/schemas/evaluation-receipt-v1.schema.json"
        ).read_text()
    )
    jsonschema.validate(payload, schema)


def test_forged_unsigned_receipt_only_establishes_self_consistency(tmp_path):
    payload = json.loads(
        Path("examples/reports/evaluation_receipt_example.json").read_text()
    )
    payload["shareable"]["evaluation"]["metrics"]["mae"] = 999.0
    path = _write(tmp_path / "forged.json", attach_integrity_metadata(payload))
    result = verify_receipt(path)
    assert result["hash_valid"] and result["valid"]
    assert result["signer_trusted"] is False and result["signature_present"] is False
    assert result["evidence_level"] == "integrity_only"
    strict = verify_receipt(path, require_trusted_signer=True)
    assert not strict["valid"] and strict["trust_reason"] == "trusted_signer_required"


def test_tampered_payload_and_rehashed_invalid_signature_are_distinct(signed):
    path, payload, trust, _ = signed
    payload["shareable"]["evaluation"]["metrics"]["mae"] = 999
    _write(path, payload)
    result = verify_receipt(path, trust_store=trust)
    assert not result["hash_valid"] and result["reason"] == "hash_check_failed"
    assert (
        result["evidence_level"] == "invalid_integrity" and not result["signer_trusted"]
    )
    payload["integrity"]["payload_sha256"] = compute_payload_sha256(payload)
    _write(path, payload)
    result = verify_receipt(path, trust_store=trust)
    assert result["hash_valid"] and result["signature_valid"] is False
    assert result["reason"] == "invalid_signature" and not result["valid"]


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"revoked": True}, "signer_key_revoked"),
        ({"signer_id": "other-lab"}, "signer_identity_mismatch"),
        ({"expires_at": "2000-01-01T00:00:00Z"}, "signer_key_expired"),
        ({"valid_from": "3000-01-01T00:00:00Z"}, "signer_key_not_yet_valid"),
    ],
)
def test_revocation_identity_and_key_validity_are_enforced(signed, change, reason):
    path, _, trust, _ = signed
    trust["keys"]["lab-a-2026"].update(change)
    result = verify_receipt(path, trust_store=trust, require_trusted_signer=True)
    assert result["signature_valid"] is True
    assert result["signer_trusted"] is False and result["reason"] == reason
    assert not result["valid"]


def test_unknown_or_wrong_pinned_key_cannot_authenticate(signed):
    path, _, trust, _ = signed
    empty = {"schema_version": "receipt-trust-store/v1", "keys": {}}
    result = verify_receipt(path, trust_store=empty, require_trusted_signer=True)
    assert result["reason"] == "unknown_signer_key" and not result["valid"]
    trust["keys"]["lab-a-2026"]["public_key"] = _public(Ed25519PrivateKey.generate())
    result = verify_receipt(path, trust_store=trust)
    assert result["reason"] == "invalid_signature" and not result["valid"]


def test_protocol_digest_is_pinned_independently_and_bound_to_signature(signed):
    path, payload, trust, _ = signed
    result = verify_receipt(path, trust_store=trust, expected_protocol_sha256="b" * 64)
    assert result["protocol_bound"] and not result["protocol_recognized"]
    assert result["reason"] == "protocol_digest_mismatch" and not result["valid"]
    payload["signer_statement"]["protocol"]["sha256"] = "b" * 64
    payload["integrity"]["payload_sha256"] = compute_payload_sha256(payload)
    result = verify_receipt(_write(path, payload), trust_store=trust)
    assert result["signature_valid"] is False


def test_protocol_identity_in_receipt_is_bound_automatically_and_cannot_conflict(
    signed,
):
    path, payload, trust, signer = signed
    source = deepcopy(payload)
    source["shareable"]["evaluation"]["protocol"] = {
        **signer["protocol"],
        "metrics": ["mae"],
        "primary_metric": "mae",
    }
    source.pop("signer_statement")
    auto = {key: value for key, value in signer.items() if key != "protocol"}
    bound = sign_artifact(source, auto)
    assert bound["signer_statement"]["protocol"] == signer["protocol"]
    assert verify_receipt(
        _write(path, bound), trust_store=trust, expected_protocol_sha256="a" * 64
    )["valid"]
    source["shareable"]["evaluation"]["protocol"]["sha256"] = "b" * 64
    with pytest.raises(ValueError, match="conflicts"):
        sign_artifact(source, signer)


def test_hmac_remains_bilateral_without_public_identity(tmp_path):
    source = json.loads(
        Path("examples/reports/evaluation_receipt_example.json").read_text()
    )
    path = _write(
        tmp_path / "hmac.json",
        attach_integrity_metadata(source, signing_secret="local-test-secret"),
    )
    result = verify_receipt(path, signing_secret="local-test-secret")
    assert result["valid"] and result["signature_valid"]
    assert (
        result["evidence_level"] == "shared_secret_integrity"
        and not result["signer_trusted"]
    )
    assert not verify_receipt(
        path, signing_secret="local-test-secret", require_trusted_signer=True
    )["valid"]


@pytest.mark.parametrize("replacement", ["unsigned-passing", "malformed"])
def test_quality_gate_uses_the_authenticated_snapshot_after_path_replacement(
    signed, tmp_path, monkeypatch, capsys, replacement
):
    path, payload, trust, signer = signed
    payload["shareable"]["evaluation"]["metrics"]["mae"] = 1.0
    _write(path, sign_artifact(payload, signer))
    incoming = deepcopy(payload)
    incoming["shareable"]["evaluation"]["metrics"]["mae"] = 0.0
    incoming.pop("signer_statement", None)
    changed = (
        json.dumps(attach_integrity_metadata(incoming))
        if replacement == "unsigned-passing"
        else "{invalid json"
    )
    store, policy = tmp_path / "trust.yaml", tmp_path / "quality.yaml"
    store.write_text(yaml.safe_dump(trust), encoding="utf-8")
    policy.write_text(
        yaml.safe_dump(
            {"schema_version": "quality-policy/v1", "metric": {"mae": {"max": 0.5}}}
        ),
        encoding="utf-8",
    )
    original = Path.read_text
    replaced = False

    def read_then_replace(self, *args, **kwargs):
        nonlocal replaced
        text = original(self, *args, **kwargs)
        if self == path and not replaced:
            replaced = True
            swapped = tmp_path / "replacement.json"
            swapped.write_text(changed, encoding="utf-8")
            swapped.replace(path)
        return text

    monkeypatch.setattr(Path, "read_text", read_then_replace)
    monkeypatch.setattr(
        "sys.argv",
        [
            "plb",
            "gate",
            str(path),
            "--policy",
            str(policy),
            "--trust-store",
            str(store),
            "--require-trusted-signer",
        ],
    )
    assert main() == 1
    result = json.loads(capsys.readouterr().out)
    assert replaced
    assert result["status"] == "fail"
    assert result["source_evidence_level"] == "authenticated_signer_statement"
    assert result["rules"][0]["observed"] == 1.0


@pytest.mark.parametrize("replacement", ["unsigned-changed", "malformed"])
def test_signing_uses_the_same_source_snapshot_that_passed_integrity(
    signed, tmp_path, monkeypatch, replacement
):
    _, payload, trust, signer = signed
    payload.pop("signer_statement", None)
    evaluation = payload["shareable"]["evaluation"]
    evaluation.update(
        metrics={"mae": 1.0}, uncertainty={}, slices={}, sample_counts={"n_samples": 8}
    )
    payload["shareable"]["privacy"].update(
        mechanism={"mode": "none"},
        release={"status": "pass", "publishable": True, "decision": "allow"},
    )
    source = _write(
        tmp_path / "hmac-source.json",
        attach_integrity_metadata(payload, signing_secret="synthetic-bilateral-secret"),
    )
    incoming = deepcopy(payload)
    incoming["shareable"]["evaluation"]["metrics"]["mae"] = 0.0
    changed = (
        json.dumps(attach_integrity_metadata(incoming))
        if replacement == "unsigned-changed"
        else "[invalid json"
    )
    policy = tmp_path / "release.yaml"
    policy.write_text(
        yaml.safe_dump(
            {
                "schema_version": "release-policy/v1",
                "id": "snapshot-regression",
                "enabled": True,
                "min_samples": 2,
                "min_cell_size": 2,
                "require_privacy_audit": False,
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "output" / "signed.json"
    original = Path.read_text
    replaced = False

    def read_then_replace(self, *args, **kwargs):
        nonlocal replaced
        text = original(self, *args, **kwargs)
        if self == source and not replaced:
            replaced = True
            swapped = tmp_path / "replacement.json"
            swapped.write_text(changed, encoding="utf-8")
            swapped.replace(source)
        return text

    monkeypatch.setattr(Path, "read_text", read_then_replace)
    monkeypatch.setattr(
        "sys.argv",
        [
            "plb",
            "sign",
            str(source),
            "--policy",
            str(policy),
            "--signing-secret",
            "synthetic-bilateral-secret",
            "--private-key",
            signer["private_key"],
            "--signer-id",
            "lab-a",
            "--key-id",
            "lab-a-2026",
            "--out",
            str(output),
        ],
    )
    assert main() == 0
    assert replaced
    result = json.loads(original(output, encoding="utf-8"))
    assert result["shareable"]["evaluation"]["metrics"]["mae"] == 1.0
    assert verify_receipt(output, trust_store=trust, require_trusted_signer=True)[
        "valid"
    ]


def test_cli_json_and_exit_codes_keep_outcomes_separate(
    signed, tmp_path, monkeypatch, capsys
):
    path, _, trust, _ = signed
    store = tmp_path / "trust.yaml"
    store.write_text(yaml.safe_dump(trust))
    monkeypatch.setattr(
        "sys.argv",
        [
            "plb",
            "verify",
            str(path),
            "--trust-store",
            str(store),
            "--require-trusted-signer",
            "--json",
        ],
    )
    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["signer_trusted"] and result["science_valid"] is None
    trust["keys"]["lab-a-2026"]["revoked"] = True
    store.write_text(yaml.safe_dump(trust))
    assert main() == 1


def test_sign_cli_uses_disclosure_boundary_and_preserves_local_source(
    signed, tmp_path, monkeypatch
):
    _, _, trust, signer = signed
    config = yaml.safe_load(Path("configs/tabular_eval.yaml").read_text())
    config["report"] = {
        "json": str(tmp_path / "run.json"),
        "markdown": str(tmp_path / "run.md"),
        "manifest": str(tmp_path / "run_manifest.json"),
    }
    config["audit"] = {"path": str(tmp_path / "audit.jsonl")}
    config_path = tmp_path / "eval.yaml"
    config_path.write_text(yaml.safe_dump(config))
    run_config(str(config_path))
    source = tmp_path / "run_receipt.json"
    original = source.read_bytes()
    policy = tmp_path / "release.yaml"
    policy.write_text(yaml.safe_dump(config["release"]))
    output = tmp_path / "signed.shareable.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "plb",
            "sign",
            str(source),
            "--policy",
            str(policy),
            "--private-key",
            signer["private_key"],
            "--signer-id",
            "lab-a",
            "--key-id",
            "lab-a-2026",
            "--out",
            str(output),
        ],
    )
    assert main() == 0
    assert source.read_bytes() == original
    assert verify_receipt(output, trust_store=trust, require_trusted_signer=True)[
        "valid"
    ]
    config["release"]["enabled"] = False
    policy.write_text(yaml.safe_dump(config["release"]))
    assert main() == 1 and not output.exists()
    assert source.read_bytes() == original
