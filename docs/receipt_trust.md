# Receipt trust and offline signatures

A receipt records a claim about an evaluation. Interpret its evidence at separate levels:

| Outcome | What it establishes |
| --- | --- |
| `hash_valid` | The payload matches its attached hash. Someone can forge both; compare against an independently trusted expected hash when tamper detection matters. |
| `signature_valid` | A pinned public key verifies the signed bytes. Without a known key this remains unknown. |
| `signer_trusted` | The key belongs to the configured signer, is not revoked, and meets local validity dates. |
| `protocol_bound` | The valid signature covers a declared protocol ID, version, and content digest. |
| `protocol_recognized` | That signed digest matches the verifier's independently supplied expected digest. |
| `execution_verified` | Always false here: signatures do not prove execution or protocol conformance. |
| `science_valid` | Unknown: signatures do not establish dataset truth, lack of contamination, or metric correctness. |

An unsigned receipt can be internally consistent even when its metrics are fabricated. Its evidence level is `integrity_only`. A trusted signature raises this to `authenticated_signer_statement`; scientific conclusions still require independent evidence. The compatibility field `valid` means the requested checks passed, not that every scientific claim is true.

## Create a local signing key

Ed25519 is optional; verification needs no account, remote registry, or internet access:

```sh
python -m pip install -e '.[signing]'
```

Run this Python snippet locally once. It writes a private PEM and a public trust store. Keep the private key in the lab's controlled environment.

```python
import base64
from pathlib import Path
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat

key = Ed25519PrivateKey.generate()
with Path("lab-private.pem").open("xb") as handle:
    handle.write(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
store = {
    "schema_version": "receipt-trust-store/v1",
    "keys": {"lab-a-2026": {"signer_id": "lab-a", "public_key": public, "revoked": False}},
}
Path("lab-public-trust.yaml").write_text(yaml.safe_dump(store), encoding="utf-8")
```

Recipients must authenticate the lab's public key through an independent channel before pinning it. A key supplied alongside an untrusted receipt does not establish the sender's identity. PrivateLabBench never trusts an embedded public key or downloads a key automatically.

## Sign an approved aggregate receipt

Create a normal local evaluation first. Save the reviewed config's `release` mapping as a standalone `release.yaml` policy, without the outer `release` key.

```sh
plb sign reports/tabular_demo_receipt.json --policy release.yaml --private-key lab-private.pem --signer-id lab-a --key-id lab-a-2026 --out reports/lab-a.signed.shareable.json
```

Signing passes through the same [disclosure boundary](privacy.md#enforced-export-policy) as other exports. A failing policy creates no signed shareable file, removes stale output, and preserves the local source. The private-key path and bytes are never included. Existing HMAC-signed local sources can use `--signing-secret`.

The signed `signer-profile/v1` statement records the signer/key ID, signing package/Python version, and optional public model/protocol identities. These are declarations by the signer, bound to the canonical payload including released metrics and the release decision. A signing runtime declaration does not attest which code originally computed imported metrics.

To bind a public protocol, supply all of `--protocol-id`, `--protocol-version`, and `--protocol-sha256`. Compute the digest from the exact public protocol bytes both parties agree on. Optional `--model-id` and `--model-revision` bind the public model identity. Local dataset hashes, paths, and identifying commitments remain local.

## Verify independently and offline

```sh
plb verify reports/lab-a.signed.shareable.json --trust-store lab-public-trust.yaml --require-trusted-signer --json
```

Add `--expected-protocol-sha256 <known-digest>` to require a particular signed protocol. A missing/different binding fails that requirement. JSON names each outcome independently and includes limitations. The CLI exits nonzero for failed integrity, bad signatures, revoked/expired/mismatched pinned identities, or unmet trust/protocol requirements.

An Ed25519 receipt without a trust store may still report internally consistent bytes; it is never labeled authenticated. Use `--require-trusted-signer` in cross-institution workflows. Legacy unsigned v1 receipts remain readable at the limited integrity level.

## Rotation and revocation

Give a rotated key a new `key_id`; keep earlier public keys when historical receipts must remain verifiable. Records may include timezone-aware `valid_from` and `expires_at`, such as `2026-01-01T00:00:00Z`. Verification checks validity at the current time. Mark compromised keys `revoked: true` and distribute the updated trust store through the authenticated channel. Offline recipients need the updated store; no central revocation service is assumed.

HMAC remains supported for bilateral local workflows, with evidence level `shared_secret_integrity`. Anyone with the symmetric secret can create a signature; it provides no independently verifiable public signer identity and cannot satisfy `--require-trusted-signer`.
