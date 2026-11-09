---
icon: material/clipboard-search-outline
---

# External validation of released models

Use the `external_validation` profile on a normal, versioned prediction-table run to describe a model evaluation on private, restricted, public, or undisclosed data. The profile adds model identity and declared provenance to ordinary metrics, uncertainty, baselines, slices, diagnostics, and receipts. It performs no model download or training.

## Declare the evaluation context

Add this section to a configuration that already names a versioned `protocol`:

```yaml
external_validation:
  schema_version: external-validation-profile/v1
  model:
    id: published-model-x
    revision: weights-v2
    artifact_sha256: REPLACE_WITH_THE_ACTUAL_64_CHARACTER_SHA256
    paper_url: https://doi.org/10.0000/replace-with-actual-reference
    citation: Replace with the model's actual citation.
  dataset:
    visibility: private
    training_overlap: unknown
    site: Local institution label
    collection_period: January through June 2026
    inclusion_criteria: Locally reviewed inclusion summary
  evaluator_relationship: independent
  relationship_statement: Explain any affiliation or involvement with model development.
```

The digest must identify the actual immutable model artifact; a mutable model name alone is insufficient. `revision` is a stable short label such as a commit or weight revision. Model paths remain in local configuration, outside this identity. Optional paper URLs must use HTTPS without credentials, query strings, or fragments. DOI and arXiv HTTPS links are suitable. Citation text and provenance statements are bounded single-line text.

Allowed evaluator relationships are `independent`, `affiliated`, `model_developer`, and `undisclosed`. Dataset visibility is `public`, `private`, `restricted`, or `undisclosed`. Training overlap is `none_known`, `known`, `unknown`, or `not_assessed`; `none_known` is a declaration about available evidence, not proof of disjointness. Describe site, collection period, inclusion criteria, and source under the optional dataset fields. These statements stay local until explicitly approved.

```sh
plb run external-validation.yaml
plb verify reports/validation_receipt.json
```

The evaluator scores one in-memory snapshot, binds its prediction artifact digest into the local profile, and uses the ordinary prediction evaluation code. With evaluation-design filtering, the digest identifies the audited frame's canonical CSV representation and records that basis explicitly. Local source paths remain local.

## Uncertainty, baselines, and robustness

Choose a protocol with scientifically appropriate uncertainty and [sampling units](sampling_design.md); the generic regression protocol supplies row-bootstrap intervals, while the official TDC point-score contracts disable them. Derive a new protocol version when changing those rules. An interval does not establish representativeness or independence from model training.

Use normal `input.baseline_prediction_column` for baseline point estimates and `input.slice_columns` for declared subgroup metrics. For paired uncertainty and practical decisions, create a separate [paired comparison](paired_comparison.md) under the same protocol:

```sh
plb compare candidate.csv baseline.csv --protocol plb://generic/regression@1.0.0 --json-report reports/validation_comparison.json
```

Retain the comparison artifact alongside the validation receipt; it has its own integrity and release checks. It is not silently embedded or treated as evidence about a different input. Add normal `diagnostics.reference_path` settings for [reference/current degradation](degradation.md). Design audits and quality gates apply in the same run.

## Approve public context explicitly

The default export omits the entire profile. A release policy can approve **exact values** under `public_validation`; this is not permission to copy arbitrary configuration or plugin metadata:

```yaml
schema_version: release-policy/v1
id: reviewed-external-validation
enabled: true
require_privacy_audit: true
include_protocol: true
public_validation:
  model:
    id: published-model-x
    revision: weights-v2
    artifact_sha256: REPLACE_WITH_THE_ACTUAL_64_CHARACTER_SHA256
  dataset:
    visibility: private
    training_overlap: unknown
  evaluator_relationship: independent
```

Supply any required privacy evidence, or explicitly review whether an empirical audit requirement is appropriate for the study; a declaration alone does not satisfy that gate. Count thresholds and [other release controls](privacy.md) still apply. Approved values must match the evaluated profile. Optional site/provenance/citation fields are included only when their exact values are also listed in the policy. A prediction digest requires explicit approval of both `prediction_artifact_sha256` and `prediction_artifact_basis`; dataset fingerprints can themselves disclose information.

The approved receipt's Markdown includes the external-validation summary. It identifies model and protocol, metrics and available intervals, approved provenance, and artifact integrity. Local rows, targets, IDs, source paths, and unapproved statements are excluded. Optional [trusted signatures](receipt_trust.md) authenticate a declared issuer and bind the artifact; self-contained hashes alone establish consistency.

## Compare independent lab results

Use the existing receipt aggregator with an additional profile check:

```sh
plb aggregate lab-a.shareable.json lab-b.shareable.json --model published-model-x@weights-v2 --require-external-validation --site lab-a --site lab-b
```

Every input must be a verified shareable receipt with an approved validation profile. Declared aggregation model identities must match those profiles, and the same model revision cannot have conflicting artifact digests. Protocol, task, metric basis, and benchmark compatibility checks remain in force. The output preserves per-site estimates and intervals; [pooling restrictions](aggregation.md) still apply. No raw data is needed. Original receipts retain each evaluator's approved provenance declarations.

The flag does not authenticate independence. Pin trusted signers when issuer identity matters. Separate model revisions or known training overlap can be examined without describing them as independent validations.

## Runnable examples

From a checkout, generate a synthetic private-like example with a small explicit JSON reference model:

```sh
python scripts/external_validation_example.py --output-dir outputs/validation-synthetic
plb verify outputs/validation-synthetic/run_receipt.shareable.json
```

An existing [TDC Caco2 cache](tdc_admet.md) enables a real public benchmark example with a constant baseline fitted to its official training/validation pool:

```sh
python scripts/external_validation_example.py --tdc-cache outputs/tdc --output-dir outputs/validation-tdc
plb verify outputs/validation-tdc/run_receipt.shareable.json
```

Both commands require an empty output directory and perform no network download. They write an actual model JSON artifact, hash it, generate local predictions, and run the normal evaluator. The public example declares `model_developer`, public data, and unassessed overlap. It demonstrates provenance and metric compatibility; it is not an independent researcher trial or a claim of competitive model performance.

## Citation and interpretation

Cite PrivateLabBench using `CITATION.cff`, the evaluated model's actual paper/artifact, the exact evaluation protocol ID/version/digest, and the source dataset where appropriate. Include the approved receipt, its integrity hash, and the trusted signer/key reference if used. Cite upstream TDC and constituent data sources for that example.

Model identity, affiliation, sampling provenance, and training-overlap descriptions are evaluator declarations. PLB does not verify that an undisclosed dataset is honestly described or representative, or that an evaluator is independent. This profile does not confer prospective, clinical, or regulatory validation status.
