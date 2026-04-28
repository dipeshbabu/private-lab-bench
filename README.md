# PrivateLabBench

PrivateLabBench is a local-first evaluation framework for scientific AI models on proprietary lab datasets.

It lets labs run model evaluations locally, compute privacy-preserving metrics, and generate benchmark reports without uploading raw experimental data. The initial product wedge is private molecular property prediction evaluation from CSV files.

## Current scope

- Molecular property prediction from `smiles,target` CSV files
- External prediction evaluation for customer-owned models
- Dependency-light hashed SMILES fingerprints
- Random forest regression/classification baseline
- Regression metrics: MAE, RMSE, R2
- Classification metrics: accuracy, F1, AUROC
- DP-style metric reporting
- Dataset and prediction summaries
- Single-client local evaluation
- Multi-client private evaluation over a directory of lab CSVs
- Weighted aggregate benchmark reports
- Markdown and JSON report export
- CLI entrypoint
- CI tests across Python 3.9, 3.10, and 3.11

## Install

```bash
pip install -e .
```

Or install minimal dependencies manually:

```bash
pip install -r requirements.txt
```

## Single-client quickstart

```bash
privatelabbench eval-molecules examples/molecules_demo.csv --target label --privacy dp --epsilon 8
```

Expected output:

```text
PrivateLabBench molecule evaluation
Task: regression
Samples: 20
Model: RandomForestRegressor
Clean metrics: ...
Reported metrics: ...
Report saved to: reports/molecule_eval_report.md
```

An example generated report is available at [`examples/reports/molecule_eval_report.md`](examples/reports/molecule_eval_report.md).

## External prediction evaluation

Evaluate predictions from a customer-owned model without integrating model code into PrivateLabBench:

```bash
privatelabbench eval-predictions examples/predictions_demo.csv \
  --target label \
  --prediction-column pred \
  --privacy dp \
  --epsilon 8 \
  --report reports/prediction_eval_report.md \
  --json-report reports/prediction_eval_report.json
```

Expected input format:

```csv
smiles,label,pred
CCO,0.12,0.14
CCN,0.20,0.23
c1ccccc1,0.74,0.71
```

This is the easiest customer workflow: they run their own model locally, add a prediction column, and PrivateLabBench generates privacy-preserving Markdown and JSON evaluation reports.

## Multi-client private evaluation

Simulate several private labs, each with its own local CSV:

```bash
privatelabbench eval-federated examples/labs --target label --privacy dp --epsilon 8
```

Expected output:

```text
PrivateLabBench federated evaluation
Clients: 3
Total samples: 60
Task type(s): regression
Model(s): RandomForestRegressor

lab_a:
  samples: 20
  clean metrics: ...
  reported metrics: ...

Aggregate reported metrics: ...
Report saved to: reports/federated_eval_report.md
```

An example federated report is available at [`examples/reports/federated_eval_report.md`](examples/reports/federated_eval_report.md).

## CSV format

```csv
smiles,label
CCO,0.12
CCN,0.20
c1ccccc1,0.74
```

For classification tasks, labels should be `0` or `1`. For regression tasks, labels can be continuous values.

## Project files

- [`docs/roadmap.md`](docs/roadmap.md): staged product and research roadmap
- [`CONTRIBUTING.md`](CONTRIBUTING.md): development and privacy principles
- [`CHANGELOG.md`](CHANGELOG.md): release notes
- [`.github/workflows/ci.yml`](.github/workflows/ci.yml): automated tests and CLI smoke tests

## Roadmap

- Config-based local runner
- JSON reports and signed run metadata
- RDKit Morgan fingerprints
- ChemBERTa and GNN model adapters
- Membership-inference and property-inference risk scoring
- Federated evaluation reports across private lab clients
- Hosted dashboard with local runner architecture
- Protein, microscopy, and materials tasks

## Non-goals for the current MVP

PrivateLabBench is not a clinical or regulated diagnostic product, does not upload raw data, and does not perform federated training yet. It is a local-first private evaluation skeleton intended to become secure scientific AI evaluation infrastructure.
