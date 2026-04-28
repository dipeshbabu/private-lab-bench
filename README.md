# PrivateLabBench

PrivateLabBench is a local-first evaluation framework for scientific AI models on proprietary lab datasets.

It lets labs run model evaluations locally, compute privacy-preserving metrics, and generate benchmark reports without uploading raw experimental data. The initial v0.1 wedge is molecular property prediction from private CSV files.

## v0.1 scope

- Molecular property prediction from `smiles,target` CSV files
- Dependency-light hashed SMILES fingerprints
- Random forest regression/classification baseline
- Regression metrics: MAE, RMSE, R2
- Classification metrics: accuracy, F1, AUROC
- DP-style metric reporting
- Dataset shift summary
- Markdown report export
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

## Quickstart

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
- [`.github/workflows/ci.yml`](.github/workflows/ci.yml): automated tests and CLI smoke test

## Roadmap

- Multi-client secure metric aggregation
- RDKit Morgan fingerprints
- ChemBERTa and GNN model adapters
- Membership-inference and property-inference risk scoring
- Federated evaluation reports across private lab clients
- Hosted dashboard with local runner architecture
- Protein, microscopy, and materials tasks

## Non-goals for v0.1

PrivateLabBench v0.1 is not a clinical or regulated diagnostic product, does not upload raw data, and does not perform federated training yet. It is a local-first private evaluation skeleton intended to become secure scientific AI evaluation infrastructure.
