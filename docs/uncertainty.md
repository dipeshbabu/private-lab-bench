# Statistical uncertainty

PrivateLabBench can estimate uncertainty for prediction-table metrics with a reproducible percentile bootstrap.

The current uncertainty schema is `uncertainty/v1`.

## Enable uncertainty

Add an `uncertainty` section to a normal prediction-table config:

```yaml
uncertainty:
  enabled: true
  method: percentile_bootstrap
  confidence_level: 0.95
  resamples: 1000
  seed: 13
  min_samples: 20
  include_slices: false
```

Then run the evaluation normally:

```bash
plb run configs/tabular_uncertainty_eval.yaml
```

No separate statistics command is required.

## Resampling scheme

Regression uses an ordinary nonparametric row bootstrap. Classification and multiclass classification use target-stratified resampling that preserves the observed class counts in each bootstrap sample. Stratification avoids making AUROC undefined merely because a bootstrap draw omitted a class.

The bootstrap is reproducible for a fixed input table, seed, resample count, and PrivateLabBench version.

Regression bootstrap calculations for MAE, RMSE, and R2 are vectorized in bounded-size batches so large private tables do not require an in-memory `resamples x rows` allocation for the full run.

## Reported fields

For each metric, PrivateLabBench records:

```text
estimate
lower
upper
valid_resamples
status
```

The uncertainty object also records:

```text
method
confidence_level
resamples
seed
sampling
n_samples
metric_basis
```

The current metric basis is `clean_metrics`: intervals describe sampling uncertainty around the exact local aggregate metric.

## Small or degenerate samples

If the evaluation has fewer rows than `min_samples`, uncertainty returns `status: skipped_min_samples` rather than manufacturing an unstable interval.

Individual metrics can also be marked:

- `undefined_point_estimate` when the metric itself is undefined;
- `insufficient_valid_resamples` when too many bootstrap replicates are undefined;
- `evaluated` when a percentile interval is available.

This matters for metrics such as R2 on constant-target resamples and AUROC in degenerate class settings.

## Slice uncertainty

Set:

```yaml
uncertainty:
  enabled: true
  include_slices: true
```

to compute intervals for configured slice metrics. Slice uncertainty is off by default because bootstrap cost grows with the number of evaluated groups. Each slice still obeys `input.min_slice_size` and `uncertainty.min_samples`.

## Privacy and sharing

Bootstrap computation uses local row-level targets and predictions, but row-level values are never written into the uncertainty object. Reports and eligible shareable receipts contain only aggregate estimates, interval bounds, and method metadata.

If a privacy release mechanism changes the published metric, PrivateLabBench does not attach a clean-metric confidence interval to that perturbed metric. The local receipt retains the clean uncertainty object, while the shareable receipt records `withheld_metric_basis_mismatch` until an uncertainty procedure specifically defined for that release mechanism exists.

## Interpretation

A confidence interval quantifies sampling uncertainty under the chosen bootstrap procedure. It does not prove that:

- the evaluation dataset is representative of future scientific data;
- the model is unbiased across unmeasured groups;
- a difference between two models is statistically significant;
- non-overlapping independent intervals are a valid paired model-comparison test.

Use the paired model-comparison workflow tracked in issue #28 for candidate-versus-baseline decisions on the same samples.

## Reproducibility guidance

For a reported result, retain the evaluation receipt and record the confidence level, number of resamples, seed, task/protocol identity, and PrivateLabBench version. Increasing the number of resamples reduces Monte Carlo noise in the reported percentile bounds but does not remove sampling uncertainty in the underlying dataset.
