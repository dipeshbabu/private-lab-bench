# PrivateLabBench

**Local-first evaluation for scientific machine learning on private data.**

PrivateLabBench evaluates model predictions on data that cannot be uploaded to a public benchmark service. Runs stay local and produce reproducible metrics, slice diagnostics, privacy-audit summaries, reports, and verifiable manifests.

> **Benchmark locally. Share evaluation artifacts, not raw data.**

PrivateLabBench is an open-source research tool. It does not require a hosted service, account, organization workspace, or remote data upload.

## Why

Scientific models are often tested on restricted distributions: unpublished experiments, internal assays, site-specific measurements, partner datasets, sensitive biomedical data, or validation sets that simply cannot be redistributed.

Public benchmarks cannot answer whether a model works on those local distributions. PrivateLabBench provides a common evaluation path that starts from a prediction table rather than requiring access to the model implementation.

## Prediction tables are the primary interface

The stable prediction-table schema is **`prediction-table/v1`**. See [`docs/prediction_tables.md`](docs/prediction_tables.md) for the protocol specification.

For regression and binary classification:

```csv
sample_id,target,prediction,site,batch
s01,0.12,0.14,lab-a,b1
s02,0.20,0.23,lab-a,b1
s03,0.33,0.31,lab-b,b2
```

`sample_id` is strongly recommended and can be required by config. IDs must be non-empty and unique when present.

Everything other than the sample ID, target, prediction columns, and optional split column is treated as metadata. Metadata values remain row-local. You can explicitly choose metadata columns for aggregate slice evaluation:

```yaml
input:
  slice_columns:
    - site
    - batch
  min_slice_size: 2
```

Slice outputs contain only group counts and aggregate metrics. Groups smaller than `min_slice_size` are suppressed.

### Multiclass tables

Multiclass evaluation uses one probability column per class:

```csv
sample_id,target,p_alpha,p_beta,p_gamma,site
m01,alpha,0.82,0.10,0.08,north
m02,beta,0.08,0.84,0.08,north
m03,gamma,0.10,0.12,0.78,south
```

Config:

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

Probability rows must be finite, bounded between 0 and 1, and sum to 1.

## 5-minute quickstart

Install from source:

```bash
git clone https://github.com/dipeshbabu/private-lab-bench.git
cd private-lab-bench
pip install -e .
```

Then:

```bash
plb list-tasks
plb validate-config configs/tabular_eval.yaml
plb run configs/tabular_eval.yaml
```

Try multiclass evaluation:

```bash
plb validate-config configs/multiclass_eval.yaml
plb run configs/multiclass_eval.yaml
```

Or evaluate a prediction table directly:

```bash
plb eval-predictions my_predictions.csv \
  --target target \
  --prediction-column prediction \
  --task-type regression \
  --sample-id-column sample_id \
  --require-sample-id \
  --slice-columns site batch
```

Both CLI names are available:

```bash
privatelabbench --help
plb --help
```

## Config format

`task:` is preferred. Existing configs using `workflow:` remain supported for compatibility.

```yaml
project: local-assay-evaluation
task: predictions

input:
  path: data/predictions.csv
  sample_id_column: sample_id
  require_sample_id: true
  target_column: target
  prediction_column: prediction
  task_type: regression
  slice_columns:
    - site
  min_slice_size: 5

privacy:
  mode: none

report:
  markdown: reports/local-assay.md
  json: reports/local-assay.json
  manifest: reports/local-assay-manifest.json
```

## What evaluation returns

Prediction-table runs can include:

- regression metrics: MAE, RMSE, R²;
- binary classification: accuracy, F1, AUROC;
- multiclass classification: accuracy, macro F1, weighted F1, log loss, macro one-vs-rest AUROC when defined;
- aggregate metrics by configured slice columns;
- prediction summaries;
- optional baseline comparison for regression/binary prediction columns;
- local membership-inference auditing for regression/binary runs with a split column;
- report integrity metadata and manifests.

Reports include a schema summary and an explicit sharing boundary. They do **not** include row-level sample IDs, targets, predictions, or metadata values.

## Current capabilities

- `prediction-table/v1` bring-your-own-predictions interface;
- regression, binary classification, and multiclass classification;
- arbitrary metadata discovery and configurable slice metrics;
- stable sample-ID validation;
- molecular property baselines with dependency-light fingerprints;
- optional RDKit Morgan fingerprints;
- multi-site/local-lab aggregate evaluation;
- model/config comparison reports;
- loss-threshold membership-inference auditing;
- experimental metric perturbation for reported metrics;
- privacy/release-policy checks;
- Markdown and JSON reports;
- config snapshots, audit logs, hashes, optional HMAC signatures, and run manifests;
- task registry with third-party Python entry-point discovery.

The current metric-perturbation mode is **not presented as a general formal differential-privacy guarantee**. Privacy hardening is tracked separately.

## Built-in tasks

```text
predictions   evaluate a local prediction table
tabular       domain-neutral prediction-table evaluation
molecules     evaluate the built-in molecular baseline
multi-site    evaluate multiple local lab/site CSVs and aggregate metrics
federated     legacy alias for multi-site
```

The `predictions` and `tabular` tasks use the same domain-independent prediction-table protocol.

## Molecular prediction example

`examples/predictions_demo.csv` demonstrates the same prediction-table interface with molecule metadata. The SMILES column is metadata; PrivateLabBench does not require molecule-specific logic to evaluate those predictions.

```bash
plb run configs/prediction_eval.yaml
```

For a built-in molecular baseline instead:

```bash
plb run configs/molecule_eval.yaml
```

## Baseline comparison

A candidate prediction column can be compared with a baseline column in the same local table:

```bash
plb run configs/prediction_with_baseline.yaml
```

## Reproducible artifacts

Config-driven runs produce a Markdown report, JSON report, audit log, and run manifest with hashes and optional HMAC signatures.

```bash
plb verify-manifest reports/kinase_prediction_manifest.json
```

See [`docs/report_integrity.md`](docs/report_integrity.md).

## Task plugins

PrivateLabBench discovers third-party task plugins through the Python entry-point group `privatelabbench.tasks`. Core extension protocols under `privatelabbench.core` cover tasks, dataset adapters, model adapters, metrics, slices, privacy audits, and artifact writers.

## Project scope

PrivateLabBench is focused on local evaluation of scientific models, restricted/private evaluation datasets, reproducible artifacts, privacy-oriented auditing, and extension across scientific domains.

It is not intended to be a hosted benchmark leaderboard, experiment tracker, ELN/LIMS, federated-training framework, or dataset hub.

See [`docs/project_scope.md`](docs/project_scope.md).

## Contributing

Contributions are welcome, especially new scientific tasks, metrics, slice diagnostics, privacy audits, benchmark/demo packs, adapters, tests, and documentation.

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Roadmap

See [`docs/roadmap.md`](docs/roadmap.md).

## License

MIT.
