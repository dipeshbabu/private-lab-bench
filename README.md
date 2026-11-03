<h1 align="center">PrivateLabBench</h1>

<p align="center">
  Evaluate scientific models on private data, from your terminal.
</p>

<p align="center">
  <a href="https://github.com/dipeshbabu/private-lab-bench/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/dipeshbabu/private-lab-bench/ci.yml?branch=main&label=build&style=flat-square"></a>
  <a href="https://github.com/dipeshbabu/private-lab-bench/blob/main/pyproject.toml"><img alt="Python 3.10, 3.11, and 3.12" src="https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue?style=flat-square"></a>
  <a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-green?style=flat-square"></a>
</p>

<p align="center">
  <a href="docs/quickstart.md">Quickstart</a> ·
  <a href="docs/prediction_tables.md">Prediction tables</a> ·
  <a href="docs/evaluation_receipts.md">Receipts</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

---

PrivateLabBench is a local evaluation framework for scientific machine learning. Bring a prediction table, measure performance across datasets and subgroups, estimate uncertainty, and compare models on matched samples. Keep the underlying data in your environment and exchange aggregate evaluation receipts with collaborators.

Evaluation runs locally without an account, hosted service, or data upload.

## Installation

Use **Python 3.10 or later**. Install from source while the first PyPI release is pending:

```sh
git clone https://github.com/dipeshbabu/private-lab-bench.git
cd private-lab-bench
python -m venv .venv
```

Activate the environment and install:

```sh
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

python -m pip install -e .
plb --help
```

The `privatelabbench` command is also available. Optional molecular featurization uses `python -m pip install -e '.[rdkit]'`. See the [installation guide](docs/install.md) for details.

## Run Your First Evaluation

Start with a bundled synthetic benchmark pack:

```sh
plb list-packs
plb run-pack community-tabular-regression@1.0.0
plb verify reports/benchmark_packs/tabular_regression_receipt.shareable.json
```

Packs include example predictions and versioned evaluation settings. They work from installed wheels and require no model downloads or training. Other packs cover molecular regression and protein binary classification.

## Evaluate Your Predictions

Use `prediction-table/v1` to evaluate outputs from your own model:

```csv
sample_id,target,prediction,site,batch
s01,0.12,0.14,lab-a,b1
s02,0.20,0.23,lab-a,b1
s03,0.33,0.31,lab-b,b2
s04,0.41,0.45,lab-b,b2
```

Save the table as `predictions.csv`, then run:

```sh
plb eval-predictions predictions.csv --target target --prediction-column prediction --task-type regression --require-sample-id --slice-columns site batch
```

Regression, binary classification, and multiclass probability tables are supported. Stable sample IDs enable validation and paired comparisons; metadata columns let you inspect performance by site, batch, or another subgroup. See the [prediction-table reference](docs/prediction_tables.md) for schemas and classification examples.

## Make Runs Reproducible

Store task, input, slice, uncertainty, and reporting settings in YAML:

```sh
plb validate-config configs/tabular_uncertainty_eval.yaml
plb run configs/tabular_uncertainty_eval.yaml
```

Config runs write local JSON and Markdown reports, an artifact manifest, and evaluation receipts. Enable bootstrap intervals explicitly and choose a sampling method appropriate to your data. See [statistical uncertainty](docs/uncertainty.md) for assumptions and limits.

Use `plb list-protocols` and `plb run local.yaml --protocol plb://generic/regression@1.0.0` to apply fixed, versioned evaluation rules across private datasets. Receipts record the exact protocol digest. See [evaluation protocols](docs/protocols.md) for local definitions, package providers, and release controls.

## Compare Models

Compare two prediction tables containing the same sample IDs and targets:

```sh
plb compare model-a.csv model-b.csv --target target --task-type regression --metric rmse --resamples 1000 --practical-threshold 0.01
```

Paired comparisons report metric differences, bootstrap intervals, and a decision relative to your practical threshold. Optional slice comparisons help locate differences across groups. See the [paired-comparison guide](docs/paired_comparison.md).

Combine compatible shared receipts with `plb aggregate lab-a.shareable.json lab-b.shareable.json --model model@revision`. The [aggregation guide](docs/aggregation.md) covers site identities, signer verification, and the metrics that support pooled point estimates.

## Inspect Evaluation Receipts

`evaluation-receipt/v1` separates local context from aggregate information intended for exchange:

| Artifact | Contents |
| --- | --- |
| `<run>_receipt.json` | Local receipt, including paths, configuration, and exact results |
| `<run>_receipt.shareable.json` | Approved aggregate receipt, written only when the export policy allows it |
| `<run>_receipt.md` | Human-readable receipt summary |

```sh
plb verify reports/tabular_uncertainty_demo_receipt.shareable.json
```

Shareable receipts require an explicit `release-policy/v1` policy. A blocked export leaves local results and a release audit, and removes any previous shareable file. The bundled synthetic packs include reviewed example policies; private-data runs need their own review. Use `plb release-check <local-receipt.json> --policy release.yaml` for a dry run.

Verification checks artifact integrity and optional signatures. A matching self-contained hash alone does not establish authorship, correct execution, or scientific validity. See [evaluation receipts](docs/evaluation_receipts.md) and [report integrity](docs/report_integrity.md).

For offline signer authentication, use optional Ed25519 signatures and pinned public keys:

```sh
plb verify receipt.shareable.json --trust-store trusted-labs.yaml --require-trusted-signer --json
```

See the [receipt trust guide](docs/receipt_trust.md) for signing, key rotation, protocol binding, and the limits of these checks.

## Privacy and Sharing

Keeping data local limits data movement; aggregate results can still disclose sensitive information. PrivateLabBench provides separate tools for exact reporting, empirical privacy audits, release-policy checks, and heuristic `metric_perturbation`.

Metric perturbation, including the deprecated `dp` alias, **does not provide a formal differential privacy guarantee**. Bounded-query DP reference primitives have their own sensitivity and accounting requirements. Read the [privacy guide](docs/privacy.md) before selecting a release method.

## Reference

Enforce explicit model thresholds in CI with `plb gate <receipt> --policy quality.yaml`.
See [quality gates](docs/quality_gates.md) for confidence, baseline, slice, and privacy requirements.

Use `--help` to explore commands and options:

```sh
plb eval-predictions --help
plb compare --help
plb list-tasks
plb list-privacy-attacks
```

- [Five-minute quickstart](docs/quickstart.md)
- [Core concepts](docs/concepts.md)
- [Tasks and plugins](docs/tasks.md)
- [Community benchmark packs](docs/benchmark_packs.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Project scope](docs/project_scope.md) and [roadmap](docs/roadmap.md)

## Developing

Install the development and documentation tools:

```sh
python -m pip install -e '.[dev,docs]' build twine
python -m pytest -q
python -m build
python -m twine check dist/*
mkdocs build
```

CI tests Python 3.10, 3.11, and 3.12, validates packages and documentation, and exercises the Docker runner. It also installs the wheel in a clean environment and runs a bundled pack outside the checkout. Release publishing uses the [tag-based release workflow](docs/releases.md).

Useful source entry points:

| Path | Purpose |
| --- | --- |
| `privatelabbench/cli.py` | Command-line interface |
| `privatelabbench/core/` | Task registry and extension interfaces |
| `privatelabbench/eval/` | Metrics, slices, uncertainty, and paired comparisons |
| `privatelabbench/privacy/` | Privacy audits and release policies |
| `privatelabbench/reports/` | Reports, receipts, and artifact integrity |
| `privatelabbench/data/` | Bundled benchmark packs and schemas |

## Contributing

Focused fixes, scientific-domain plugins, benchmark packs, and documentation improvements are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) for setup, extension boundaries, and validation requirements. Discuss new tasks, privacy methods, or schema changes in an issue before implementation.

The project follows its [Code of Conduct](CODE_OF_CONDUCT.md) and [governance guide](GOVERNANCE.md). Report sensitive vulnerabilities through the process in [SECURITY.md](SECURITY.md).

## License

Released under the [MIT license](LICENSE). Use [CITATION.cff](CITATION.cff) to cite PrivateLabBench in research.
