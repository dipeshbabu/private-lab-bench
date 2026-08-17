# Prediction Table Protocol

PrivateLabBench uses a domain-independent prediction-table protocol so researchers can evaluate outputs from any model without integrating model code into the framework.

The current schema version is **`prediction-table/v1`**.

## Core fields

A prediction table has three conceptual parts:

- a stable sample identifier;
- a target/ground-truth column;
- one or more prediction columns.

For regression and binary classification, one prediction column is used:

```csv
sample_id,target,prediction
s01,0.12,0.14
s02,0.20,0.23
```

For multiclass classification, use one probability column per class:

```csv
sample_id,target,p_alpha,p_beta,p_gamma
m01,alpha,0.82,0.10,0.08
m02,beta,0.08,0.84,0.08
m03,gamma,0.10,0.12,0.78
```

The order of the multiclass probability columns is bound explicitly to `class_labels` in the config.

## Stable sample IDs

`sample_id` is the default identifier column. Stable IDs are strongly recommended because they make reordered or independently generated prediction tables easier to compare and reproduce.

When a sample-ID column is present:

- every value must be non-empty;
- every value must be unique.

To make IDs mandatory:

```yaml
input:
  sample_id_column: sample_id
  require_sample_id: true
```

If `require_sample_id` is false, validation emits a warning when the configured ID column is absent.

## Prediction columns

### Regression

Use one numeric prediction column:

```yaml
input:
  target_column: target
  prediction_column: prediction
  task_type: regression
```

### Binary classification

Use one probability column for the positive/second class. Probabilities must be between 0 and 1.

String labels are supported. The class order can be made explicit:

```yaml
input:
  target_column: target
  prediction_column: probability_positive
  task_type: classification
  class_labels:
    - negative
    - positive
```

### Multiclass classification

Use multiple probability columns plus one class label for each column:

```yaml
input:
  target_column: target
  prediction_columns:
    - p_alpha
    - p_beta
    - p_gamma
  class_labels:
    - alpha
    - beta
    - gamma
  task_type: multiclass
```

Each probability row must:

- contain finite numeric values;
- stay within `[0, 1]`;
- sum to `1.0` within a small numerical tolerance.

## Metadata

Columns that are not the target, prediction columns, sample ID, or split column are treated as metadata. PrivateLabBench does not need to know their domain semantics.

Examples include:

- `site`;
- `batch`;
- `assay`;
- `target_family`;
- `time`;
- `series`;
- any project-specific grouping field.

You may optionally require metadata columns with `metadata_columns`.

## Slice evaluation

Only columns explicitly listed under `slice_columns` are aggregated into slice metrics:

```yaml
input:
  slice_columns:
    - site
    - batch
  min_slice_size: 5
```

For each slice value, the report contains:

- sample count;
- status (`evaluated` or `skipped_min_slice_size`);
- aggregate task metrics when the group is large enough.

Rows from groups smaller than `min_slice_size` are not reported with metrics. This reduces accidental disclosure from very small groups, but it is not by itself a formal privacy guarantee.

## Supported problem types

`prediction-table/v1` supports:

- regression: MAE, RMSE, R²;
- binary classification: accuracy, F1, AUROC;
- multiclass classification: accuracy, macro F1, weighted F1, log loss, and macro one-vs-rest AUROC when defined.

## Optional membership split

A `split_column` can identify member/train and nonmember/test rows for the built-in loss-threshold membership-inference audit.

This audit currently supports regression and binary classification. Multiclass privacy auditing is intentionally rejected rather than silently applying an incompatible attack.

## Sharing boundary

Prediction tables remain local. Aggregate prediction reports may include:

- schema column names;
- task metrics;
- prediction summaries;
- configured slice counts and metrics;
- privacy-audit summaries;
- report/manifest integrity metadata.

Aggregate reports do **not** include row-level:

- sample IDs;
- targets;
- predictions/probabilities;
- metadata values tied to individual rows.

The local source path can appear in local reports for reproducibility. A separate evaluation-receipt artifact with explicit local/private versus shareable fields is tracked in issue #6.

## Included examples

- `configs/tabular_eval.yaml` — generic regression with site/batch slices;
- `configs/prediction_eval.yaml` — molecular predictions evaluated through the same generic interface;
- `configs/multiclass_eval.yaml` — multiclass probability-table evaluation;
- `configs/prediction_with_baseline.yaml` — candidate-versus-baseline comparison.
