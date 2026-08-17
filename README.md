# PrivateLabBench

**Local-first evaluation for scientific machine learning on private data.**

PrivateLabBench helps researchers evaluate models on datasets that cannot be uploaded to a public benchmark service. Evaluations run locally and produce reproducible reports, manifests, privacy-audit summaries, and verifiable artifact hashes.

> **Benchmark locally. Share evaluation artifacts, not raw data.**

PrivateLabBench is an open-source research tool. It does not require a hosted service, account, organization workspace, or remote data upload.

## Why

Scientific model evaluation often happens on restricted data: unpublished experimental measurements, proprietary assay or chemistry datasets, partner or multi-site datasets, sensitive biomedical or laboratory records, and internal validation distributions that cannot be redistributed.

Public benchmarks are useful, but they cannot answer whether a model works on a private local distribution. PrivateLabBench provides a common local evaluation path and reproducible artifacts for those cases.

## Current capabilities

- bring-your-own-predictions evaluation from local CSV files;
- regression and binary-classification metrics;
- molecular property baselines with dependency-light fingerprints;
- optional RDKit Morgan fingerprints;
- multi-site/local-lab aggregate evaluation;
- model/config comparison reports;
- error and distribution summaries;
- loss-threshold membership-inference auditing;
- experimental metric perturbation for reported metrics;
- privacy/release-policy checks;
- Markdown and JSON reports;
- config snapshots, audit logs, hashes, optional HMAC signatures, and run manifests;
- a task registry with third-party Python entry-point discovery.

The current metric-perturbation mode is **not presented as a general formal differential-privacy guarantee**.

## Install

```bash
git clone https://github.com/dipeshbabu/private-lab-bench.git
cd private-lab-bench
pip install -e .
```

Development install:

```bash
pip install -e '.[dev]'
```

Optional RDKit support:

```bash
pip install -e '.[rdkit]'
```

Both CLI names are available:

```bash
privatelabbench --help
plb --help
```

## 5-minute quickstart

```bash
plb list-tasks
plb validate-config configs/tabular_eval.yaml
plb run configs/tabular_eval.yaml
```

Or evaluate your own prediction table directly:

```bash
plb eval-predictions my_predictions.csv --target target --prediction-column prediction --task-type regression
```

Minimal prediction table:

```csv
sample_id,target,prediction
s01,0.12,0.14
s02,0.20,0.23
s03,0.33,0.31
```

## Config format

`task:` is preferred. Existing configs using `workflow:` remain supported for compatibility.

```yaml
project: local-assay-evaluation
task: predictions
input:
  path: data/predictions.csv
  target_column: target
  prediction_column: prediction
  task_type: regression
privacy:
  mode: none
report:
  markdown: reports/local-assay.md
  json: reports/local-assay.json
  manifest: reports/local-assay-manifest.json
```

## Built-in tasks

```text
predictions   evaluate a local prediction table
tabular       domain-neutral prediction-table evaluation
molecules     evaluate the built-in molecular baseline
multi-site    evaluate multiple local lab/site CSVs and aggregate metrics
federated     legacy alias for multi-site
```

The built-in `tabular` task intentionally contains no molecule-specific assumptions.

## Bring your own predictions

The prediction-table path is the lowest-friction interface. Your model can be implemented in PyTorch, JAX, scikit-learn, R, Julia, a notebook, or another system. PrivateLabBench only needs the local targets and predictions.

Baseline comparison is supported with `configs/prediction_with_baseline.yaml`.

## Molecular evaluation

```bash
plb run configs/molecule_eval.yaml
```

With RDKit installed:

```bash
plb run configs/molecule_eval_rdkit.yaml
```

## Multi-site evaluation

```bash
plb run configs/federated_eval.yaml
```

The current built-in multi-site evaluator is molecule-oriented. The task/plugin refactor will continue removing those assumptions.

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
