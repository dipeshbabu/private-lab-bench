from privatelabbench.attestation import (
    ATTESTATION_ID_ENV,
    CODE_REVISION_ENV,
    RUNNER_IMAGE_DIGEST_ENV,
    collect_runner_attestation,
)


def test_runner_attestation_excludes_host_identifiers(monkeypatch):
    monkeypatch.delenv(CODE_REVISION_ENV, raising=False)
    monkeypatch.delenv(RUNNER_IMAGE_DIGEST_ENV, raising=False)
    monkeypatch.delenv(ATTESTATION_ID_ENV, raising=False)

    claim = collect_runner_attestation()

    assert claim["schema_version"] == "runner-attestation/v0.1"
    assert claim["package"]["name"] == "private-lab-bench"
    assert claim["attestation_id"]
    assert "hostname" not in claim
    assert "username" not in claim
    assert "cwd" not in claim


def test_runner_attestation_accepts_managed_runner_metadata(monkeypatch):
    monkeypatch.setenv(CODE_REVISION_ENV, "abc123")
    monkeypatch.setenv(RUNNER_IMAGE_DIGEST_ENV, "sha256:deadbeef")
    monkeypatch.setenv(ATTESTATION_ID_ENV, "attestation-1")

    claim = collect_runner_attestation()

    assert claim["code_revision"] == "abc123"
    assert claim["runner_image_digest"] == "sha256:deadbeef"
    assert claim["attestation_id"] == "attestation-1"
