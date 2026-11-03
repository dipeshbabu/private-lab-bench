"""Offline receipt signatures authenticate a signer, never evaluation execution."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import platform
from pathlib import Path
import re
from typing import Any, Mapping

from privatelabbench import __version__
from privatelabbench.reports.integrity import canonical_json, compute_payload_sha256

LIMITATIONS = [
    "A self-contained hash establishes internal consistency, not authorship.",
    "A trusted signature authenticates the signer's statement, not execution or protocol conformance.",
    "Scientific validity, dataset truth, training overlap, and metric correctness are not independently established.",
]
PUBLIC_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,199}\Z")
DIGEST = re.compile(r"[a-f0-9]{64}\Z")


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not PUBLIC_ID.fullmatch(value):
        raise ValueError("Signer and claim identities must be explicit public identifiers")
    return value


def _receipt_protocol(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    shared = payload.get("shareable")
    evaluation = shared.get("evaluation") if isinstance(shared, Mapping) else None
    protocol = evaluation.get("protocol") if isinstance(evaluation, Mapping) else None
    return protocol if isinstance(protocol, Mapping) else None


def sign_artifact(payload: Mapping[str, Any], signer: Mapping[str, Any]) -> dict[str, Any]:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError as exc:
        raise ValueError("Install the optional signing extra to use Ed25519") from exc
    statement = {
        "schema_version": "signer-profile/v1",
        "signer_id": _identifier(signer.get("signer_id")),
        "key_id": _identifier(signer.get("key_id")),
        "evaluation_code": {"package_version": __version__, "python_version": platform.python_version()},
        "provenance": "declared_by_signer",
    }
    protocol = signer.get("protocol")
    receipt_protocol = _receipt_protocol(payload)
    if receipt_protocol:
        claimed = {key: receipt_protocol.get(key) for key in ("id", "version", "sha256")}
        if protocol is not None and protocol != claimed:
            raise ValueError("Signer protocol conflicts with the protocol in the approved receipt")
        protocol = claimed
    if protocol is not None:
        if not isinstance(protocol, Mapping) or not isinstance(protocol.get("sha256"), str) or not DIGEST.fullmatch(protocol["sha256"]):
            raise ValueError("Protocol binding requires a SHA-256 content digest")
        statement["protocol"] = {"id": _identifier(protocol.get("id")), "version": _identifier(protocol.get("version")), "sha256": protocol["sha256"]}
    model = signer.get("model")
    if model is not None:
        if not isinstance(model, Mapping):
            raise ValueError("Invalid public model identity")
        statement["model"] = {"id": _identifier(model.get("id")), "revision": _identifier(model.get("revision"))}
    key = load_pem_private_key(Path(signer["private_key"]).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Only Ed25519 private keys are supported")
    signed = dict(payload)
    signed["signer_statement"] = statement
    signature = key.sign(canonical_json(signed))
    signed["integrity"] = {"algorithm": "sha256", "payload_sha256": compute_payload_sha256(signed), "signed": True, "signature_algorithm": "ed25519", "signature": base64.b64encode(signature).decode("ascii")}
    return signed


def _date(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("Trust-store validity dates require a time zone")
    return timestamp


def verify_trust(payload: Mapping[str, Any], *, trust_store: Mapping[str, Any] | None = None, require_trusted_signer: bool = False, expected_protocol_sha256: str | None = None) -> dict[str, Any]:
    integrity = payload.get("integrity", {})
    algorithm = integrity.get("signature_algorithm")
    present = bool(integrity.get("signature"))
    result = {"signature_present": present, "signature_valid": None, "signer_trusted": False, "protocol_bound": False, "protocol_recognized": False, "model_identity_bound": False, "evidence_level": "integrity_only", "execution_verified": False, "science_valid": None, "limitations": list(LIMITATIONS), "trust_reason": "unsigned", "trust_requirements_met": not require_trusted_signer}
    if trust_store is not None and (not isinstance(trust_store, Mapping) or trust_store.get("schema_version") != "receipt-trust-store/v1" or not isinstance(trust_store.get("keys"), Mapping)):
        return {**result, "trust_reason": "invalid_trust_store", "trust_requirements_met": False}
    if expected_protocol_sha256 is not None and (not isinstance(expected_protocol_sha256, str) or not DIGEST.fullmatch(expected_protocol_sha256)):
        return {**result, "trust_reason": "invalid_expected_protocol_digest", "trust_requirements_met": False}
    if not present:
        if require_trusted_signer:
            result.update(trust_reason="trusted_signer_required", trust_requirements_met=False)
    elif algorithm == "hmac-sha256":
        result["trust_reason"] = "symmetric_signature_requires_shared_secret"
    elif algorithm != "ed25519":
        result.update(trust_reason="unsupported_signature_algorithm", signature_valid=False, trust_requirements_met=False)
    else:
        statement = payload.get("signer_statement")
        if not isinstance(statement, Mapping) or statement.get("schema_version") != "signer-profile/v1":
            return {**result, "trust_reason": "invalid_signer_profile", "signature_valid": False, "trust_requirements_met": False}
        try:
            if set(statement) - {"schema_version", "signer_id", "key_id", "evaluation_code", "provenance", "protocol", "model"}:
                raise ValueError("Unsupported signer profile fields")
            code = statement.get("evaluation_code")
            if not isinstance(code, Mapping) or set(code) != {"package_version", "python_version"} or not all(isinstance(value, str) for value in code.values()) or statement.get("provenance") != "declared_by_signer":
                raise ValueError("Invalid signer provenance")
            _identifier(statement.get("signer_id"))
            key_id = _identifier(statement.get("key_id"))
            if "model" in statement:
                model = statement["model"]
                if not isinstance(model, Mapping) or set(model) != {"id", "revision"}:
                    raise ValueError("Invalid model statement")
                _identifier(model["id"])
                _identifier(model["revision"])
            if "protocol" in statement:
                protocol = statement["protocol"]
                if not isinstance(protocol, Mapping) or set(protocol) != {"id", "version", "sha256"} or not isinstance(protocol.get("sha256"), str) or not DIGEST.fullmatch(protocol["sha256"]):
                    raise ValueError("Invalid protocol statement")
                _identifier(protocol["id"])
                _identifier(protocol["version"])
            if trust_store is None:
                result["trust_reason"] = "no_trust_store"
            else:
                if not isinstance(trust_store, Mapping) or trust_store.get("schema_version") != "receipt-trust-store/v1" or not isinstance(trust_store.get("keys"), Mapping):
                    raise ValueError("Invalid trust store")
                key_info = trust_store["keys"].get(key_id)
                if key_info is None:
                    result["trust_reason"] = "unknown_signer_key"
                    result["trust_requirements_met"] = False
                else:
                    from cryptography.exceptions import InvalidSignature
                    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
                    if not isinstance(key_info, Mapping) or not isinstance(key_info.get("revoked", False), bool):
                        raise ValueError("Invalid key record")
                    public = base64.b64decode(key_info["public_key"], validate=True)
                    signature = base64.b64decode(integrity["signature"], validate=True)
                    try:
                        Ed25519PublicKey.from_public_bytes(public).verify(signature, canonical_json(payload))
                        result["signature_valid"] = True
                    except InvalidSignature:
                        result.update(signature_valid=False, trust_reason="invalid_signature", trust_requirements_met=False)
                    if result["signature_valid"]:
                        now = datetime.now(timezone.utc)
                        if key_info.get("signer_id") != statement["signer_id"]:
                            result["trust_reason"] = "signer_identity_mismatch"
                        elif key_info.get("revoked", False):
                            result["trust_reason"] = "signer_key_revoked"
                        elif key_info.get("valid_from") and now < _date(key_info["valid_from"]):
                            result["trust_reason"] = "signer_key_not_yet_valid"
                        elif key_info.get("expires_at") and now >= _date(key_info["expires_at"]):
                            result["trust_reason"] = "signer_key_expired"
                        else:
                            result.update(signer_trusted=True, trust_reason="trusted_signer", evidence_level="authenticated_signer_statement", trust_requirements_met=True)
        except ImportError:
            result.update(trust_reason="signing_dependency_missing", trust_requirements_met=False)
        except (ValueError, TypeError, KeyError):
            result.update(trust_reason="invalid_trust_store_or_signature_encoding", trust_requirements_met=False)
        protocol = statement.get("protocol")
        protocol_declared = isinstance(protocol, Mapping) and isinstance(protocol.get("sha256"), str) and bool(DIGEST.fullmatch(protocol["sha256"])) and bool(protocol.get("id")) and bool(protocol.get("version"))
        result["protocol_bound"] = bool(protocol_declared and result["signature_valid"])
        receipt_protocol = _receipt_protocol(payload)
        if receipt_protocol and (not protocol_declared or any(protocol.get(key) != receipt_protocol.get(key) for key in ("id", "version", "sha256"))):
            result.update(protocol_bound=False, trust_requirements_met=False, trust_reason="receipt_protocol_statement_mismatch")
        if expected_protocol_sha256 is not None:
            result["protocol_recognized"] = bool(result["protocol_bound"] and protocol["sha256"] == expected_protocol_sha256)
        result["model_identity_bound"] = bool(isinstance(statement.get("model"), Mapping) and result["signature_valid"])
    if require_trusted_signer and not result["signer_trusted"]:
        result["trust_requirements_met"] = False
    # Revoked/mismatched pinned identities must never silently downgrade to hash-only success.
    if result["trust_reason"] in {"signer_key_revoked", "signer_key_expired", "signer_key_not_yet_valid", "signer_identity_mismatch"}:
        result["trust_requirements_met"] = False
    if expected_protocol_sha256 is not None and not result["protocol_recognized"]:
        result.update(trust_reason="protocol_digest_mismatch" if result["protocol_bound"] else "protocol_binding_unavailable", trust_requirements_met=False)
    return result
