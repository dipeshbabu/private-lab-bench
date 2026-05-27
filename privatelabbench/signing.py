from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping


RUNNER_PRIVATE_KEY_ENV = "PRIVATELABBENCH_RUNNER_PRIVATE_KEY"
RUNNER_PUBLIC_KEYS_ENV = "PRIVATELABBENCH_RUNNER_PUBLIC_KEYS"
RUNNER_PUBLIC_KEYS_FILE_ENV = "PRIVATELABBENCH_RUNNER_PUBLIC_KEYS_FILE"
SIGNATURE_ALGORITHM = "ed25519"


def payload_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_key_material(value: str) -> str:
    candidate = Path(value)
    if candidate.exists() and candidate.is_file():
        return candidate.read_text(encoding="utf-8")
    return value


def _crypto_imports() -> tuple[object, object, object, object]:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Signed sync requires cryptography. Install with: pip install -e '.[api]'") from exc
    return InvalidSignature, serialization, Ed25519PrivateKey, Ed25519PublicKey


def _load_private_key(value: str) -> object:
    _, serialization, Ed25519PrivateKey, _ = _crypto_imports()
    key_material = _read_key_material(value).encode("utf-8")
    key = serialization.load_pem_private_key(key_material, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Runner private key must be an Ed25519 PEM key.")
    return key


def _load_public_key(value: str) -> object:
    _, serialization, _, Ed25519PublicKey = _crypto_imports()
    key_material = _read_key_material(value).encode("utf-8")
    key = serialization.load_pem_public_key(key_material)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Runner public key must be an Ed25519 PEM key.")
    return key


def sign_payload(payload: bytes, private_key: str) -> str:
    key = _load_private_key(private_key)
    return base64.b64encode(key.sign(payload)).decode("ascii")


def verify_payload_signature(payload: bytes, public_key: str, signature: str) -> bool:
    InvalidSignature, _, _, _ = _crypto_imports()
    key = _load_public_key(public_key)
    try:
        key.verify(base64.b64decode(signature.encode("ascii")), payload)
    except (InvalidSignature, ValueError):
        return False
    return True


def load_runner_public_keys() -> dict[str, str]:
    registry: dict[str, str] = {}
    registry_file = os.getenv(RUNNER_PUBLIC_KEYS_FILE_ENV)
    if registry_file:
        payload = json.loads(Path(registry_file).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Runner public key registry file must contain a JSON object.")
        registry.update({str(key): str(value) for key, value in payload.items()})

    inline = os.getenv(RUNNER_PUBLIC_KEYS_ENV)
    if inline:
        payload = json.loads(inline)
        if not isinstance(payload, dict):
            raise ValueError("Runner public key registry must be a JSON object.")
        registry.update({str(key): str(value) for key, value in payload.items()})
    return registry


def verification_result(
    *,
    payload: bytes,
    headers: Mapping[str, str | None],
    public_keys: Mapping[str, str] | None = None,
) -> dict[str, object]:
    registry = dict(public_keys) if public_keys is not None else load_runner_public_keys()
    runner_id = headers.get("x-runner-id") or headers.get("X-Runner-ID")
    signature = headers.get("x-runner-signature") or headers.get("X-Runner-Signature")
    algorithm = headers.get("x-runner-signature-alg") or headers.get("X-Runner-Signature-Alg")
    signed_hash = headers.get("x-runner-payload-sha256") or headers.get("X-Runner-Payload-SHA256")
    actual_hash = payload_sha256(payload)

    if not registry:
        return {
            "required": False,
            "verified": None,
            "runner_id": runner_id,
            "algorithm": algorithm,
            "payload_sha256": actual_hash,
            "reason": "runner_signature_not_required",
        }
    if not runner_id or not signature:
        return {
            "required": True,
            "verified": False,
            "runner_id": runner_id,
            "algorithm": algorithm,
            "payload_sha256": actual_hash,
            "reason": "missing_runner_signature",
        }
    if runner_id not in registry:
        return {
            "required": True,
            "verified": False,
            "runner_id": runner_id,
            "algorithm": algorithm,
            "payload_sha256": actual_hash,
            "reason": "unknown_runner",
        }
    if algorithm != SIGNATURE_ALGORITHM:
        return {
            "required": True,
            "verified": False,
            "runner_id": runner_id,
            "algorithm": algorithm,
            "payload_sha256": actual_hash,
            "reason": "unsupported_signature_algorithm",
        }
    if signed_hash and signed_hash != actual_hash:
        return {
            "required": True,
            "verified": False,
            "runner_id": runner_id,
            "algorithm": algorithm,
            "payload_sha256": actual_hash,
            "reason": "payload_hash_mismatch",
        }

    verified = verify_payload_signature(payload, registry[runner_id], signature)
    return {
        "required": True,
        "verified": verified,
        "runner_id": runner_id,
        "algorithm": algorithm,
        "payload_sha256": actual_hash,
        "reason": "ok" if verified else "invalid_signature",
    }
