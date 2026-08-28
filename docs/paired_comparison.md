# Paired model comparison

PrivateLabBench can compare two models on the **same private evaluation samples** without treating their metric estimates as independent.

The comparison protocol is `paired-comparison/v1`, and the local/shareable result artifact is `paired-comparison-artifact/v1`.

## Why paired comparison

If Model A and Model B both predict the same samples, their errors are paired. Comparing two independent confidence intervals throws away that structure and can give a misleading impression of whether one model is actually better.

PrivateLabBench instead aligns the two prediction tables by stable `sample_id` and resamples/swaps the matched rows together.

## Basic usage

Regression:

```bash
plb compare candidate.csv baseline.csv \
  --target target \
  --prediction-column prediction \
  --task-type regression \
  --metric rmse
```

Binary classification:

```bash
plb compare candidate.csv baseline.csv \
  --target target \
  --prediction-column probability_positive \
  --task-type classification \
  --class-labels negative positive \
  --metric auroc \
  --practical-threshold 0.01
```

Multiclass:

```bash
plb compare candidate.csv baseline.csv \
  --target target \
  --prediction-columns p_alpha p_beta p_gamma \
  --class-labels alpha beta gamma \
  --task-type multiclass \
  --metric log_loss
```

When `--target` is omitted, `plb compare` keeps the existing config-level comparison behavior for backwards compatibility.

## Exact sample alignment

Paired mode requires both files to contain exactly the same stable sample IDs.

PrivateLabBench:

- rejects missing or duplicate sample IDs;
- rejects sample IDs that occur in only one table;
- reorders Model B to Model A's sample-ID order;
- verifies that targets agree for every aligned sample;
- verifies that configured slice metadata agrees for every aligned sample;
- never performs an inner join that silently drops unmatched rows.

This is important because silently comparing a convenient intersection can change the scientific question being answered.

## Metric direction and improvement

The artifact records both:

```text
raw_delta_a_minus_b
improvement_a_over_b
```

`raw_delta_a_minus_b` is literally `metric_A - metric_B`.

`improvement_a_over_b` is direction adjusted so that **positive always means Model A is better**:

- AUROC, accuracy, F1, R²: `A - B`;
- MAE, RMSE, log loss: `B - A`.

This makes downstream thresholds and quality gates unambiguous.

## Paired bootstrap interval

The default uncertainty method is a percentile paired bootstrap.

For every bootstrap replicate, the same resampled sample IDs are used for both models. Regression uses ordinary row resampling. Classification and multiclass comparison use target-stratified resampling so observed class counts are preserved.

The reported interval is an interval for `improvement_a_over_b`, not two independent model intervals.

Example:

```text
Model A AUROC      0.824
Model B AUROC      0.807
Improvement        +0.017
95% paired CI      [+0.006, +0.029]
```

The resample count, confidence level, seed, sampling strategy, valid resample count, and point estimate are stored in the artifact.

## Paired randomization test

PrivateLabBench also provides a paired prediction-swap randomization test.

Under the exchangeability null, each matched sample independently swaps which model's prediction is called A versus B. The selected metric difference is recomputed after those within-sample swaps.

The current test reports a two-sided Monte Carlo p-value with a plus-one correction.

Use:

```bash
plb compare a.csv b.csv \
  --target target \
  --metric rmse \
  --permutations 5000
```

Set `--permutations 0` to disable the test.

A small p-value is statistical evidence against the prediction-exchangeability null. It is **not** a measure of practical importance.

## Practical superiority threshold

Use `--practical-threshold` to distinguish a scientifically meaningful improvement from a tiny nonzero difference:

```bash
plb compare a.csv b.csv \
  --target target \
  --metric auroc \
  --practical-threshold 0.01
```

The threshold is expressed in direction-adjusted metric units. For the example above, Model A must improve AUROC by at least `0.01`.

The artifact reports separate decisions for:

- the observed point estimate;
- the paired confidence interval.

A threshold of zero still treats an exact tie as a tie/inconclusive result rather than declaring Model A superior because of an inclusive comparison at zero.

## Noninferiority

An optional `--noninferiority-margin` asks whether Model A can be ruled out as worse than Model B by more than a user-specified amount.

For a margin `m`, noninferiority is established only when the lower bound of the direction-adjusted paired interval is at least `-m`.

Example:

```bash
plb compare candidate.csv baseline.csv \
  --target target \
  --metric rmse \
  --noninferiority-margin 0.02
```

The margin is domain policy, not a universal statistical constant. It should be chosen from scientific, clinical, operational, or experimental relevance before looking at the result when possible.

## Slice comparison

Use shared metadata columns to ask whether a globally better model loses on an important subgroup:

```bash
plb compare candidate.csv baseline.csv \
  --target target \
  --metric rmse \
  --slice-columns site batch
```

For each eligible group, PrivateLabBench reports:

- sample count;
- Model A selected metric;
- Model B selected metric;
- direction-adjusted improvement;
- A/B/tie winner.

Small groups are skipped according to `--min-slice-size`.

Add `--include-slice-uncertainty` to run a paired bootstrap inside each eligible slice. This can be computationally expensive and should be interpreted carefully when many groups are scanned.

### Multiple comparisons

Scanning many slices increases the chance of seeing an apparently extreme subgroup by chance. PrivateLabBench reports the slice evidence but does not currently apply an automatic multiplicity correction. Do not interpret a large collection of exploratory slice intervals or p-values as pre-registered confirmatory tests.

## Artifacts and sharing boundary

A paired comparison writes:

```text
comparison.json
comparison.shareable.json
comparison.md
```

The local JSON artifact contains local prediction-table paths and SHA256 hashes for reproducibility.

The independently verifiable shareable artifact contains only aggregate comparison evidence such as:

- model names;
- task and metric identity;
- sample count;
- exact-alignment status;
- model metrics;
- paired interval;
- randomization test summary;
- practical/noninferiority decisions;
- aggregate slice comparison.

It does **not** contain:

- prediction-table paths;
- sample-ID values;
- targets;
- predictions/probabilities;
- row-level metadata.

Verify it with:

```bash
plb verify reports/model_comparison.shareable.json
```

The machine-readable schema is bundled at `privatelabbench/data/schemas/paired-comparison-artifact-v1.schema.json`.

## Interpretation limits

Paired comparison answers whether two models differ on the **observed matched evaluation distribution** under the selected resampling/randomization procedures. It does not prove that:

- the private dataset is representative of future deployment data;
- a statistically detectable difference is scientifically important;
- a slice difference is causal;
- the selected practical or noninferiority threshold is appropriate for every domain.

Use statistical evidence, effect size, practical threshold, slice behavior, and domain context together.
