from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Mapping

INTEGRITY_FIELD = "integrity"


def canonical_json(payload: Mapping[str, Any]) -> bytes:
    unsigned = {k: v for k, v in payload.items() if k != INTEGRITY_FIELD}
    return json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def compute_payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def sign_payload(payload: Mapping[str, Any], secret: str) -> str:
    if not secret:
        raise ValueError("Signing secret must not be empty.")
    return hmac.new(
        secret.encode("utf-8"), canonical_json(payload), hashlib.sha256
    ).hexdigest()


def attach_integrity_metadata(
    payload: dict[str, Any], *, signing_secret: str | None = None
) -> dict[str, Any]:
    payload = dict(payload)
    integrity: dict[str, Any] = {
        "algorithm": "sha256",
        "payload_sha256": compute_payload_sha256(payload),
        "signed": bool(signing_secret),
    }
    if signing_secret:
        integrity["signature_algorithm"] = "hmac-sha256"
        integrity["signature"] = sign_payload(payload, signing_secret)
    payload[INTEGRITY_FIELD] = integrity
    return payload


def verify_report(
    path: str,
    *,
    signing_secret: str | None = None,
    trust_store: Mapping[str, Any] | None = None,
    require_trusted_signer: bool = False,
    expected_protocol_sha256: str | None = None,
) -> dict[str, Any]:
    report_path = Path(path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        **verify_payload(
            payload,
            signing_secret=signing_secret,
            trust_store=trust_store,
            require_trusted_signer=require_trusted_signer,
            expected_protocol_sha256=expected_protocol_sha256,
        ),
        "path": str(report_path),
    }


def verify_payload(
    payload: Any,
    *,
    signing_secret: str | None = None,
    trust_store: Mapping[str, Any] | None = None,
    require_trusted_signer: bool = False,
    expected_protocol_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify the exact in-memory snapshot consumed by a downstream operation."""
    integrity = payload.get(INTEGRITY_FIELD) if isinstance(payload, dict) else None
    if not isinstance(integrity, dict):
        from privatelabbench.reports.trust import LIMITATIONS

        return {
            "valid": False,
            "hash_valid": False,
            "signature_present": False,
            "signature_valid": None,
            "signer_trusted": False,
            "protocol_bound": False,
            "evidence_level": "invalid_integrity",
            "execution_verified": False,
            "science_valid": None,
            "limitations": list(LIMITATIONS),
            "reason": "missing_integrity_metadata",
        }

    expected_hash = integrity.get("payload_sha256")
    actual_hash = compute_payload_sha256(payload)
    hash_valid = bool(expected_hash) and hmac.compare_digest(
        str(expected_hash), actual_hash
    )

    signature_valid = None
    if signing_secret and integrity.get("signature_algorithm") != "ed25519":
        expected_signature = integrity.get("signature")
        actual_signature = sign_payload(payload, signing_secret)
        signature_valid = bool(expected_signature) and hmac.compare_digest(
            str(expected_signature), actual_signature
        )

    valid = hash_valid and (signature_valid is not False)
    reason = "ok" if valid else "integrity_check_failed"
    if signing_secret and signature_valid is False:
        reason = "signature_check_failed"
    if not hash_valid:
        reason = "hash_check_failed"

    from privatelabbench.reports.trust import verify_trust

    trust = verify_trust(
        payload,
        trust_store=trust_store,
        require_trusted_signer=require_trusted_signer,
        expected_protocol_sha256=expected_protocol_sha256,
    )
    if integrity.get("signature_algorithm") == "hmac-sha256":
        trust["signature_valid"] = signature_valid
        if signature_valid is True:
            trust["evidence_level"] = "shared_secret_integrity"
            trust["trust_reason"] = (
                "shared_secret_verified_without_public_signer_identity"
            )
    elif integrity.get("signature_algorithm") == "ed25519":
        signature_valid = trust["signature_valid"]
    if not hash_valid:
        trust.update(
            evidence_level="invalid_integrity",
            signer_trusted=False,
            protocol_bound=False,
            protocol_recognized=False,
            model_identity_bound=False,
        )
    valid = valid and signature_valid is not False and trust["trust_requirements_met"]
    if hash_valid and not trust["trust_requirements_met"]:
        reason = trust["trust_reason"]
    elif (
        hash_valid
        and signature_valid is False
        and integrity.get("signature_algorithm") != "hmac-sha256"
    ):
        reason = trust["trust_reason"]
    return {
        **trust,
        "valid": valid,
        "reason": reason,
        "payload_sha256": actual_hash,
        "expected_payload_sha256": expected_hash,
        "hash_valid": hash_valid,
        "signature_valid": signature_valid,
        "signed": bool(integrity.get("signed")),
    }
