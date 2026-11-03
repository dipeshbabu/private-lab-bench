# Reference/current performance diagnostics

Use two prediction tables from the same model and scoring setup to inspect where performance changed:

```bash
plb evaluate current.csv --reference reference.csv \
  --slice site --slice batch --primary-metric rmse \
  --degradation-threshold 0.03 --independent-cohorts \
  --include-slice-uncertainty \
  --numeric-metadata assay_signal --categorical-metadata instrument
```

Column and task choices follow the [evaluate workflow](quickstart.md). Both tables must have unique stable IDs, compatible targets, prediction columns, and ordered class labels. Missing targets/predictions are rejected so the comparison cannot silently change its populations. The current table's ordinary metrics, quality gate, and receipt remain available alongside the diagnostics.

## Interpret changes in context

`degradation-summary/v1` is recorded in the local report and receipt. It contains overall changes for supported metrics, slice changes, ranked improvements/degradations for the primary metric, new or missing slice values, prevalence changes, and explicitly selected distribution diagnostics.

Positive degradation always means worse current performance: `current - reference` for MAE/RMSE/log loss, and `reference - current` for accuracy/AUROC/R²/F1. Relative degradation divides that direction-adjusted change by the absolute reference value. A zero or undefined reference yields an undefined relative change. `--degradation-threshold` is an absolute practical threshold in primary-metric units; other metric thresholds can be declared in YAML. These are user policy, not universal scientific cutoffs.

Overall stability can hide a degraded subgroup if another subgroup improved. Conversely, overall performance can worsen because the current cohort contains more difficult cases while every within-slice score stays stable. Read the slice prevalence fields before interpreting the overall change. Missing/new groups carry explicit statuses and no imputed zero metric. Small groups retain counts locally but do not receive invented performance estimates or intervals.

Target/prediction distributions are summarized automatically. Additional numeric/categorical features require explicit flags. Numeric summaries report means, standard deviations, missing counts, standardized mean change using the reference standard deviation, and an empirical CDF distance (KS distance). A constant reference makes the standardized change undefined. Categorical summaries report missing counts and total variation distance across observed proportions. Distances are descriptive: no distribution-test p-value or causal attribution is made. Performance change alone is not evidence of a particular distribution shift.

## Uncertainty assumptions

Without `--independent-cohorts`, point changes are available and delta intervals say `independence_not_declared`. The flag declares independent observations within and between cohorts. The independent percentile bootstrap draws the two cohorts separately, using the same core regression/target-stratified classification routines as ordinary evaluation, deterministic spawned random streams, and bounded temporary memory for regression.

Overlapping sample IDs withhold unpaired delta intervals, even after the independence flag, because matching identifiers may represent repeated observations. For genuinely paired predictions on the same samples and targets, use [paired comparison](paired_comparison.md). Renaming IDs does not establish independence. Repeated patients, compounds, batches, or nested laboratories need an appropriate sampling design before a row bootstrap can support an inference.

Both cohorts must meet the configured uncertainty minimum, and at least 80% of resamples (at least 20) must produce a defined metric. Undefined metrics and insufficient evidence remain explicit. Slice intervals additionally require `--include-slice-uncertainty` (or `uncertainty.include_slices: true`); a protocol's fixed settings still apply. They are exploratory, unadjusted intervals: scanning many slices does not produce confirmatory or causal evidence. Practical point thresholds and confidence intervals answer different questions.

## Reusable YAML

`plb init current.csv --reference reference.csv --slice site --independent-cohorts` generates a config. The diagnostic section can also be supplied in an existing prediction-table config:

```yaml
diagnostics:
  reference_path: reference.csv
  independent_cohorts: true
  practical_thresholds:
    rmse: 0.03
    mae: 0.02
  prevalence_threshold: 0.10
  numeric_metadata: [assay_signal]
  categorical_metadata: [instrument]
```

The current input schema and protocol settings apply to the reference too. Changing units, positive-class meaning, or the model between cohorts invalidates the intended interpretation; receipts cannot independently establish those facts. Diagnostic metrics use clean predictions. If reported current metrics are perturbed, the disclosure boundary withholds clean degradation diagnostics.

## Approve public diagnostics explicitly

Diagnostics stay local by default, even when ordinary current-cohort aggregate metrics are approved. Extend a reviewed `release-policy/v1` only after considering both cohorts:

```yaml
include_degradation: true
public_shift_features: [target, prediction, assay_signal, instrument]
slices:
  site: [lab-a, lab-b]
```

This fragment supplements the policy's schema, ID, enabled flag, count thresholds, and audit requirements. Both reference and current counts must satisfy the release minimum. Only the explicitly approved complete slice partition can be published; absent/new/unexpected labels or a small cell in either cohort withhold the entire partition. Distribution features need their own explicit aliases; category labels and raw identifiers are never exported, and small category/missingness cells withhold that feature.

Public JSON and Markdown include only the approved summary. The writer recomputes changes and ranks, drops private paths and arbitrary metadata, and applies the repeated-release ledger. A self-consistent receipt or trusted signer still does not establish model execution, dataset truth, independence, or scientific validity.

This diagnostic workflow does not run a separate membership-inference audit on the reference cohort. A release policy requiring such privacy evidence cannot publish diagnostics based only on the current cohort's audit. Keep them local or use a disclosure policy explicitly reviewed for this exact aggregate release; existing failed upstream gates still block publication.
