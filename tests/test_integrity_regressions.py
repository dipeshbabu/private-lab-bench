import json

import pytest

from privatelabbench.reports.integrity import attach_integrity_metadata, verify_payload
from privatelabbench.reports.manifest import verify_run_manifest


@pytest.mark.parametrize("field", ["payload_sha256", "signature"])
@pytest.mark.parametrize(
    "value", ["\u00e9" * 64, ["not", "a", "digest"], {"invalid": True}, 12, None]
)
def test_malformed_digest_is_invalid_evidence_instead_of_a_verifier_crash(field, value):
    payload = attach_integrity_metadata(
        {"schema_version": "test/v1"}, signing_secret="test-secret"
    )
    payload["integrity"][field] = value
    result = verify_payload(payload, signing_secret="test-secret")
    assert result["valid"] is False


@pytest.mark.parametrize("field", ["payload_sha256", "signature"])
def test_manifest_verification_rejects_non_ascii_digests(tmp_path, field):
    payload = attach_integrity_metadata({"artifacts": []}, signing_secret="test-secret")
    payload["integrity"][field] = "\u00e9" * 64
    source = tmp_path / "manifest.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    assert verify_run_manifest(source, signing_secret="test-secret")["valid"] is False
