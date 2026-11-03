# Evaluation Receipts

PrivateLabBench evaluation receipts are stable artifacts for communicating the result of a local evaluation without making the local run directory or private dataset part of the sharing protocol.

The current schema is **`evaluation-receipt/v1`**. Its [machine-readable JSON Schema](https://github.com/dipeshbabu/private-lab-bench/blob/v0.1.1/privatelabbench/data/schemas/evaluation-receipt-v1.schema.json) ships with the package.

## Three local outputs

A config-driven run writes its local report, manifest, full receipt, and Markdown
summary. A shareable receipt is created only when an explicit `release-policy/v1`
policy permits export:

```text
<run>_receipt.json
<run>_receipt.shareable.json
<run>_receipt.md
```

The full JSON receipt has `scope: local`. It contains two explicitly separated sections:

- `shareable` — the local candidate aggregate results; this section must pass the exporter before sharing;
- `local` — paths, config snapshot, exact local metrics, runner identity, and full attestation metadata.

The `*.receipt.shareable.json` file has `scope: shareable` and contains **no `local` section**. It is independently hashed/signed, so removing the local section does not invalidate its integrity metadata.

An allowed Markdown receipt is rendered from the sanitized export. A blocked
export instead writes a local explanation and a `*.shareable.release-audit.json`
decision record. Any previous shareable JSON is removed. See the
[export-policy guide](privacy.md#enforced-export-policy).

## Shareable section

`shareable` contains:

- fresh export identity and timestamp, without private project labels;
- explicitly approved public benchmark ID/version/suite/domain/protocol;
- minimal input schema, with column names only when explicitly approved;
- aggregate sample counts;
- released/reported metrics;
- optional uncertainty fields when a task supplies them;
- one explicitly approved slice partition when all categories meet cell thresholds;
- privacy-audit summary and release-gate status;
- package identity; local attestation and source artifact names/hashes are withheld.

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

The exporter accepts explicitly released metrics in this order:

1. `reported_metrics`;
2. `aggregate_reported_metrics`.

A candidate containing only clean metrics cannot be exported. Exact reporting is
still supported when the evaluator explicitly records it as `reported_metrics`.

Exact `clean_metrics`/`aggregate_clean_metrics` remain in the local section when available.

This separation is important for privacy mechanisms: future formal release mechanisms can change how reported metrics are produced without changing the receipt schema.

## Verify a receipt

Use the [receipt trust guide](receipt_trust.md) for Ed25519 signatures, offline
public-key pinning, rotation/revocation, and protocol binding. Unsigned and legacy
receipts remain readable with explicitly limited integrity semantics.

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
- the shareable receipt selects approved aggregate material and receives its own integrity metadata; source artifact names/hashes remain local.

The full local receipt retains manifest-bound artifact hashes. Receipts are not
inserted back into the source manifest, avoiding circular artifact hashing.

## Example

See the [v0.1.1 example receipt](https://github.com/dipeshbabu/private-lab-bench/blob/v0.1.1/examples/reports/evaluation_receipt_example.json) for a fixed, valid shareable receipt.
