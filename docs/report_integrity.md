# Report Integrity, Manifests, and Receipts

PrivateLabBench uses three related artifact layers. They solve different problems and intentionally remain separate.

## 1. JSON reports

Task reports contain local evaluation results plus an `integrity` block with a canonical SHA256 payload digest and optional HMAC signature.

```bash
plb verify-report reports/kinase_prediction_eval.json
```

## 2. Run manifests

Config-driven runs write `run-manifest/v0.1`, which binds concrete local artifacts:

- config file;
- JSON report;
- Markdown report;
- audit log;
- benchmark/task identity;
- runner provenance/attestation;
- file SHA256 hashes.

Because manifests contain local paths, they are primarily reproducibility and local verification artifacts.

```bash
plb verify-manifest reports/kinase_prediction_manifest.json
```

The manifest format remains backward compatible. Existing manifest verification behavior is unchanged by evaluation receipts.

## 3. Evaluation receipts

After a config-driven manifest is written, PrivateLabBench also creates:

```text
<run>_receipt.json
<run>_receipt.shareable.json
<run>_receipt.md
```

`evaluation-receipt/v1` separates:

- `shareable`: released metrics, input-schema summary, aggregate slices, privacy/release status, benchmark identity, provenance ID, and artifact names/hashes;
- `local`: local paths, config snapshot, exact metrics, runner details, and full attestation.

The shareable JSON receipt omits the `local` section entirely and has its own integrity digest/signature. The Markdown receipt is rendered only from the shareable section.

See [`evaluation_receipts.md`](evaluation_receipts.md).

## Generic verifier

`plb verify` detects the artifact schema and dispatches to the appropriate verifier:

```bash
plb verify reports/kinase_prediction_receipt.shareable.json
plb verify reports/kinase_prediction_manifest.json
plb verify reports/kinase_prediction_eval.json
```

The explicit legacy commands remain available.

## Optional local signing

```bash
export PRIVATELABBENCH_SIGNING_SECRET="local-signing-secret"
plb run configs/prediction_eval.yaml
plb verify reports/kinase_prediction_receipt.shareable.json \
  --signing-secret "$PRIVATELABBENCH_SIGNING_SECRET"
```

Reports, manifests, local receipts, and shareable receipts are independently HMAC-signed when signing is enabled.

The signing key remains local. Integrity signing proves only that the signed payload has not changed relative to the provided secret; it does not provide confidentiality or differential privacy.

## Config snapshot and audit log

Config-driven JSON reports record the YAML settings used for the local run. Runs also write a JSONL audit event with evaluation metadata and report paths, not raw dataset rows.

Config snapshots and paths belong to local artifacts and are intentionally excluded from shareable receipts.
