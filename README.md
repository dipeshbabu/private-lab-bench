# PrivateLabBench

[![CI](https://github.com/dipeshbabu/private-lab-bench/actions/workflows/ci.yml/badge.svg)](https://github.com/dipeshbabu/private-lab-bench/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)
![License](https://img.shields.io/badge/license-MIT-green)

**Local-first evaluation for scientific machine learning on private data.**

PrivateLabBench evaluates model predictions on data that cannot be uploaded to a public benchmark service. Runs stay local and produce reproducible metrics, slice diagnostics, privacy-audit summaries, reports, manifests, and shareable evaluation receipts.

> **Benchmark locally. Share evaluation artifacts, not raw data.**

PrivateLabBench is an open-source research tool. It does not require a hosted service, account, organization workspace, or remote data upload.

## Install

**Current state:** the project is release-ready but the first PyPI release has not been confirmed yet. Until a real PyPI release exists, install from source:

```bash
git clone https://github.com/dipeshbabu/private-lab-bench.git
cd private-lab-bench
pip install -e .
```

After the first successful PyPI Trusted Publishing release, the intended install command is:

```bash
pip install private-lab-bench
```

Do not rely on that PyPI command until a release is actually present on PyPI.

## 5-minute quickstart

```bash
plb list-packs
plb run-pack community-tabular-regression@1.0.0
plb verify reports/benchmark_packs/tabular_regression_receipt.shareable.json
```

Then evaluate your own prediction table:

```bash
plb eval-predictions predictions.csv \
  --target target \
  --prediction-column prediction \
  --sample-id-column sample_id \
  --require-sample-id \
  --slice-columns site batch
```

Both CLI names are available:

```bash
plb --help
privatelabbench --help
```

## Prediction tables are the primary interface

`prediction-table/v1` lets researchers evaluate outputs from any model without integrating model code.

Regression/binary example:

```csv
sample_id,target,prediction,site,batch
s01,0.12,0.14,lab-a,b1
s02,0.20,0.23,lab-a,b1
s03,0.33,0.31,lab-b,b2
```

PrivateLabBench supports:

- regression;
- binary classification, including string labels;
- multiclass probability tables;
- arbitrary metadata columns;
- configurable aggregate slices;
- stable sample-ID validation;
- local membership-inference auditing for supported tasks.

See [`docs/prediction_tables.md`](docs/prediction_tables.md).

## Evaluation receipts

Config-driven runs create:

```text
<run>_receipt.json
<run>_receipt.shareable.json
<run>_receipt.md
```

`evaluation-receipt/v1` separates local-only information such as paths/config snapshots/exact metrics from the independently verifiable shareable section.

```bash
plb verify reports/kinase_prediction_receipt.shareable.json
```

See [`docs/evaluation_receipts.md`](docs/evaluation_receipts.md).

## Community benchmark packs

Bundled versioned packs demonstrate the same evaluation protocol without model training/downloads:

```text
community-molecules-regression@1.0.0
community-tabular-regression@1.0.0
community-proteins-binary@1.0.0
```

They are packaged with installed wheels, not dependent on the repository working directory.

```bash
plb list-packs
plb run-pack community-proteins-binary@1.0.0
```

See [`docs/benchmark_packs.md`](docs/benchmark_packs.md).

## Privacy semantics

PrivateLabBench deliberately separates:

- exact aggregate reporting;
- heuristic `metric_perturbation` (no formal DP guarantee);
- empirical privacy attacks/audits;
- bounded-query DP reference primitives with explicit sensitivity/accounting;
- release-policy gates.

The historical `mode: dp` spelling is deprecated and means heuristic metric perturbation, **not** formal differential privacy.

See [`docs/privacy.md`](docs/privacy.md).

## Extensible core

The task registry supports built-ins and third-party Python entry points. Extension protocols cover:

- tasks;
- dataset/model adapters;
- metrics/slices;
- privacy audits;
- artifact writers.

```bash
plb list-tasks
plb list-privacy-attacks
```

## Documentation

A MkDocs Material site lives in `docs/` and is validated in CI:

```bash
pip install -e '.[docs]'
mkdocs serve
```

Start with:

- [`docs/install.md`](docs/install.md)
- [`docs/quickstart.md`](docs/quickstart.md)
- [`docs/concepts.md`](docs/concepts.md)
- [`docs/troubleshooting.md`](docs/troubleshooting.md)

## Package/release verification

CI builds the sdist/wheel, runs Twine metadata checks, installs the wheel into a clean virtual environment outside the source checkout, and verifies bundled packs still run.

A tag-triggered release workflow is prepared for PyPI Trusted Publishing. Actual publication requires the external PyPI Trusted Publisher to be configured first; see [`docs/releases.md`](docs/releases.md).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md), [`GOVERNANCE.md`](GOVERNANCE.md), and [`SECURITY.md`](SECURITY.md).

## Project scope

PrivateLabBench is focused on standardized local evaluation of scientific models, private/restricted evaluation distributions, reproducible artifacts, privacy-oriented auditing, and scientific-domain extensions.

It is not a hosted leaderboard, experiment tracker, ELN/LIMS, federated-training framework, or dataset hub.

See [`docs/project_scope.md`](docs/project_scope.md).

## License

MIT.
