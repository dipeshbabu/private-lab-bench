# Hidden benchmark owner workflow

Evaluate prediction submissions locally against owner-held labels, then publish explicitly approved aggregate receipts and a receipt-only results table. `hidden-benchmark/v1` pins an evaluation protocol and keeps owner dataset paths local. It supports regression, binary probabilities, and ordered multiclass probabilities.

## Choose how models receive inputs

`approved_participant_inputs` means the owner has approved participants' access to the required model inputs and opaque sample IDs. Participants return only IDs and predictions; labels stay with the owner. PLB does not distribute input features or decide whether those features may be disclosed.

`owner_only` means inputs stay inside the lab. Ordinary participant predictions are rejected. Run a reviewed model with the [trusted local scorer](trusted_scoring.md), then supply its snapshot-bound scoring provenance. That scorer has no security sandbox and accepts only its reviewed numeric reference format. Submitted containers, executables, pickle files, remote/custom Python, and untrusted model execution are unsupported.

The owner-only provenance check detects mismatched prediction/model artifacts. It is an owner declaration backed by local file hashes, not independent proof of execution or protection against a malicious model/runtime.

## Define the local owner specification

```yaml
schema_version: hidden-benchmark/v1
id: private-assay-challenge
version: 1.0.0
protocol: protocol.yaml
protocol_sha256: REPLACE_WITH_THE_ACTUAL_PROTOCOL_DIGEST
input_access: approved_participant_inputs
private_input:
  path: private/owner-labels.csv
  sample_id_column: sample_id
  target_column: target
  slice_columns: []
submission:
  sample_id_column: sample_id
  prediction_column: prediction
```

Paths resolve relative to the specification. Pin the actual canonical digest shown by `plb show-protocol protocol.yaml`; changed definitions fail. The protocol must require stable sample IDs. Change the benchmark version when the hidden test set changes, and the protocol version when scientific rules change.

For multiclass tasks, replace `prediction_column` with an ordered `prediction_columns` list matching the protocol's ordered classes. Required/optional slices and count/audit floors remain bound by the protocol. An owner release override cannot waive a required evaluation-design audit.

For approved participant inputs, create a template containing only IDs and blank prediction columns:

```sh
plb benchmark-template owner.yaml --out outputs/submission-template.csv
```

Templates are disabled for owner-only inputs. They never contain targets, feature values, or private metadata. Existing files are preserved. Use opaque IDs that do not themselves encode sensitive outcomes.

## Evaluate a submission

```sh
plb benchmark-evaluate owner.yaml predictions.csv --submission-id submission-001 --model published-model@weights-v2 --output-dir reports/submission-001
```

Submission columns must exactly match the declared ID/prediction schema. Targets, features, extra columns, duplicate/missing/unknown IDs, incomplete predictions, and invalid probabilities fail. Shuffled submissions are aligned to the exact owner record set; records are never silently dropped or deduplicated. Explicit class-label strings retain their spelling, including leading zeroes.

An optional `--submission-manifest submission.yaml` records participant/citation metadata locally and can pin the actual prediction file digest:

```yaml
schema_version: submission-manifest/v1
id: submission-001
model:
  id: published-model
  revision: weights-v2
prediction_sha256: REPLACE_WITH_THE_ACTUAL_PREDICTION_FILE_DIGEST
participant: Optional local participant description
citation: Optional local model citation
```

The manifest identity must agree with the explicit command. Participant descriptions and citation notes stay local. The aggregate `benchmark-submission/v1` identity contains the submission ID, declared model/revision, actual submitted prediction-file SHA-256, and evaluation mode. A prediction file hash does not prove which model generated it.

Owner-only inputs require a separate explicit scoring step and its matching provenance:

```sh
plb score --model approved-model.yaml --data private/features.csv --units feature-units.yaml --output outputs/model-predictions.csv
plb benchmark-evaluate owner-only.yaml outputs/model-predictions.csv --submission-id submission-001 --model published-model@weights-v2 --scoring-provenance outputs/model-predictions.score.json --output-dir reports/submission-001
```

Use an empty owner output directory for each evaluation. It contains a **private normalized evaluation CSV with targets**, configuration, provenance, local reports, and receipts. Share only the approved `.shareable.json` receipt and its approved Markdown summary. Do not share the whole report directory. Failed reruns clear stale public JSON/Markdown outputs while preserving inputs. CLI rejection messages avoid echoing hidden targets or IDs; detailed owner-side Python exceptions should remain in the owner's environment.

## Approve aggregate publication

Add an explicit `release` policy to the local specification:

```yaml
release:
  schema_version: release-policy/v1
  id: reviewed-challenge-results
  enabled: true
  require_privacy_audit: false
  include_protocol: true
  include_submission: true
  public_benchmark:
    id: private-assay-challenge
    version: 1.0.0
    suite: owner-hidden-benchmark
    protocol: prediction-table/v1
  public_models:
    - id: published-model
      revision: weights-v2
  public_submission_ids: [submission-001]
```

The example assumes the owner separately reviewed the study's privacy requirements; configure required empirical/design evidence appropriately. Count floors, approved complete slice partitions, upstream privacy/design gates, and repeated-query controls still apply. Missing required evidence blocks publication. There is no automatic public export without reviewed consent.

Publication requires matching benchmark ID/version and protocol identity plus explicitly approved submission/model identities. It includes the submitted prediction-file digest, never owner label hashes, owner paths, raw IDs, targets, features, participant notes, or arbitrary inference logs. Verification checks artifact consistency and optional [trusted owner signatures](receipt_trust.md); it does not independently establish honest scoring or hidden test-set identity.

## Build a verified results table

```sh
plb benchmark-leaderboard submission-a.shareable.json submission-b.shareable.json --protocol protocol.yaml --out reports/leaderboard.json
```

The table consumes only verified, already-shareable submission receipts with matching benchmark, protocol digest, task, fixed test count, and metric basis. Duplicate submissions, model revisions, or receipts fail. Use `--trust-store` and `--require-trusted-signer` to authenticate a pinned benchmark owner. No raw data or prediction tables are needed by the table builder.

There is **no ranking by default**. A results table remains unranked unless its full pinned evaluation protocol explicitly declares a rule:

```yaml
ranking:
  metric: mae
  rule: conservative_interval_ties
  practical_tie_tolerance: 0.02
  require_uncertainty: true
```

The ranking metric must be the protocol's primary metric. This scientific change requires a new protocol version/digest. With required uncertainty, missing/undefined estimates or intervals leave the whole table unranked. Overlapping or practically close marginal bounds form conservative connected rank groups. Groups can connect transitively; membership does not establish pairwise equality. Bounds widen to contain their point estimate if necessary, preserving conservative grouping. The interval sweep is linear after sorting.

Setting `require_uncertainty: false` explicitly chooses descriptive point/tolerance groups; missing intervals do not become zero-width uncertainty claims. Period/model scans are exploratory, not multiplicity-adjusted paired tests or a simultaneous confidence statement. The owner can use [paired comparison](paired_comparison.md) on local normalized prediction tables for a separate, properly scoped comparison artifact.

To publish a leaderboard and Markdown table, supply `--release-policy` with the same explicit protocol/benchmark/model/submission approvals, covering every included row. The exporter validates the full protocol definition against its digest, recomputes rank groups, and reapplies sample/unit floors. `include_source_receipts: true` additionally approves hashes of already-shareable source receipts. Local full definitions and source verification context stay local.

## Runnable synthetic walkthrough

From a checkout:

```sh
python scripts/hidden_benchmark_example.py --mode owner-only --output-dir outputs/hidden-owner-demo
plb verify outputs/hidden-owner-demo/leaderboard.shareable.json
```

`--mode participant` demonstrates approved participant-input semantics instead. Both modes generate synthetic observations and invented numeric reference models, evaluate two submissions, verify aggregate receipt inputs, and publish only the explicitly approved synthetic results. They perform no network download and make no claim about real hidden scientific data, independent researcher trials, or validated model performance.

## Threat and execution boundaries

This is an owner-side hidden-data workflow, not a complete anti-cheating system. It does not prove that owner labels, model revisions, or scoring statements are honest; prevent an owner from selecting favorable submissions; or eliminate test-set leakage, adaptive overfitting, and inference from repeated aggregate queries. Apply governance, access controls, query review, and appropriate privacy methods to the study.

Future untrusted model/container execution needs an independently reviewed executor with enforced filesystem, resource, egress, and output restrictions. The versioned trusted adapter boundary exists for reviewed local scoring; this benchmark command executes no submitted model code and does not silently route untrusted submissions to that trusted interface.
