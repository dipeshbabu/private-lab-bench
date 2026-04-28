from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Mapping

INTEGRITY_FIELD = "integrity"


def canonical_json(payload: Mapping[str, Any]) -> bytes:
    unsigned = {k: v for k, v in payload.items() if k != INTEGRITY_FIELD}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def sign_payload(payload: Mapping[str, Any], secret: str) -> str:
    if not secret:
        raise ValueError("Signing secret must not be empty.")
    return hmac.new(secret.encode("utf-8"), canonical_json(payload), hashlib.sha256).hexdigest()


def attach_integrity_metadata(payload: dict[str, Any], *, signing_secret: str | None = None) -> dict[str, Any]:
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


def verify_report(path: str, *, signing_secret: str | None = None) -> dict[str, Any]:
    report_path = Path(path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    integrity = payload.get(INTEGRITY_FIELD)
    if not isinstance(integrity, dict):
        return {"valid": False, "reason": "missing_integrity_metadata", "path": str(report_path)}

    expected_hash = integrity.get("payload_sha256")
    actual_hash = compute_payload_sha256(payload)
    hash_valid = bool(expected_hash) and hmac.compare_digest(str(expected_hash), actual_hash)

    signature_valid = None
    if signing_secret:
        expected_signature = integrity.get("signature")
        actual_signature = sign_payload(payload, signing_secret)
        signature_valid = bool(expected_signature) and hmac.compare_digest(str(expected_signature), actual_signature)

    valid = hash_valid and (signature_valid is not False)
    reason = "ok" if valid else "integrity_check_failed"
    if signing_secret and signature_valid is False:
        reason = "signature_check_failed"
    if not hash_valid:
        reason = "hash_check_failed"

    return {
        "valid": valid,
        "reason": reason,
        "path": str(report_path),
        "payload_sha256": actual_hash,
        "expected_payload_sha256": expected_hash,
        "hash_valid": hash_valid,
        "signature_valid": signature_valid,
        "signed": bool(integrity.get("signed")),
    }
