# Evaluation Receipts

PrivateLabBench evaluation receipts are stable artifacts for communicating the result of a local evaluation without making the local run directory or private dataset part of the sharing protocol.

The current schema is **`evaluation-receipt/v1`**. A machine-readable JSON Schema is checked in at [`schemas/evaluation-receipt-v1.schema.json`](../schemas/evaluation-receipt-v1.schema.json).

## Three local outputs

A config-driven run writes its existing report and run manifest, then creates:

```text
<run>_receipt.json
<run>_receipt.shareable.json
<run>_receipt.md
```

The full JSON receipt has `scope: local`. It contains two explicitly separated sections:

- `shareable` — aggregate evaluation results intended to be safe to extract/share under the run's release policy;
- `local` — paths, config snapshot, exact local metrics, runner identity, and full attestation metadata.

The `*.receipt.shareable.json` file has `scope: shareable` and contains **no `local` section**. It is independently hashed/signed, so removing the local section does not invalidate its integrity metadata.

The Markdown receipt is rendered only from the shareable section.

## Shareable section

`shareable` contains:

- run ID, project, task, report type, and run timestamp;
- benchmark ID/version/suite/domain/protocol;
- input schema summary;
- aggregate sample counts;
- released/reported metrics;
- optional uncertainty fields when a task supplies them;
- aggregate configured slice metrics;
- privacy-audit summary and release-gate status;
- package version and privacy-preserving attestation ID;
- artifact **names + SHA256 hashes**, without local paths.

For prediction-table tasks, the input schema is `prediction-table/v1` and includes only column/schema metadata—not row values.

## Local section

The full local receipt can contain:

- artifact/config paths;
- config snapshot;
- exact clean metrics;
- runner identity;
- full local runner attestation;
- source manifest integrity metadata.

This section is explicitly marked `sharing: local_only`.

## Metric selection

The shareable receipt prefers released metrics in this order:

1. `reported_metrics`;
2. `aggregate_reported_metrics`;
3. exact metrics only when no separate reported-metric field exists.

Exact `clean_metrics`/`aggregate_clean_metrics` remain in the local section when available.

This separation is important for privacy mechanisms: future formal release mechanisms can change how reported metrics are produced without changing the receipt schema.

## Verify a receipt

Use the generic verifier:

```bash
plb verify reports/tabular_demo_receipt.shareable.json
```

It also understands existing report and run-manifest formats:

```bash
plb verify reports/tabular_demo_eval.json
plb verify reports/tabular_demo_manifest.json
```

The existing explicit commands remain available:

```bash
plb verify-report ...
plb verify-manifest ...
```

When receipts are HMAC-signed:

```bash
plb verify receipt.shareable.json --signing-secret "$PRIVATELABBENCH_SIGNING_SECRET"
```

## Legacy manifest compatibility

`run-manifest/v0.1` remains unchanged and is still verified by the manifest verifier.

PrivateLabBench can normalize a legacy manifest into an in-memory `evaluation-receipt/v1` compatibility view. The compatibility view includes only information that really existed in the old manifest. Missing metrics, input schema, and release results are labeled as unavailable rather than fabricated.

## Relationship to manifests

A receipt is **not** a replacement for the local run manifest.

- the manifest binds concrete local files and paths for reproducibility/verification;
- the receipt presents a stable evaluation/result schema;
- the shareable receipt removes local-only material while preserving artifact hashes and independently verifiable integrity metadata.

This avoids circular artifact hashing: receipts reference manifest-bound artifact hashes, but receipts are not themselves inserted back into the source manifest.

## Example

See [`examples/reports/evaluation_receipt_example.json`](../examples/reports/evaluation_receipt_example.json) for a fixed, valid shareable receipt.
