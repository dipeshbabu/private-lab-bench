<h1 align="center">PrivateLabBench</h1>

<p align="center">
  Evaluate scientific models on private data, from your terminal.
</p>

<p align="center">
  <a href="https://pypi.org/project/private-lab-bench/"><img alt="PyPI" src="https://img.shields.io/pypi/v/private-lab-bench?style=flat-square"></a>
  <a href="https://github.com/dipeshbabu/private-lab-bench/actions/workflows/ci.yml"><img alt="Build" src="https://img.shields.io/github/actions/workflow/status/dipeshbabu/private-lab-bench/ci.yml?branch=main&label=build&style=flat-square"></a>
  <a href="https://github.com/dipeshbabu/private-lab-bench/blob/main/pyproject.toml"><img alt="Python 3.10, 3.11, and 3.12" src="https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue?style=flat-square"></a>
  <a href="https://github.com/dipeshbabu/private-lab-bench/blob/main/LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-green?style=flat-square"></a>
</p>

<p align="center">
  <a href="https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/quickstart.md">Quickstart</a> ·
  <a href="https://github.com/dipeshbabu/private-lab-bench/tree/main/docs">Documentation</a> ·
  <a href="https://github.com/dipeshbabu/private-lab-bench/releases/tag/v0.1.0">v0.1.0 release</a> ·
  <a href="https://github.com/dipeshbabu/private-lab-bench/blob/main/CONTRIBUTING.md">Contributing</a>
</p>

---

PrivateLabBench is a local evaluation framework for scientific machine learning. Bring model predictions and a validation table to compare candidates, estimate uncertainty, and find failures across sites, assays, or other groups. Keep the underlying data in your environment and share approved aggregate receipts with collaborators.

Evaluation runs without an account, hosted service, or data upload. A receipt records the evaluation protocol, selected results, and the evidence available to verify them.

## Installation

The current release is **v0.1.0**, available on [PyPI](https://pypi.org/project/private-lab-bench/0.1.0/) and [GitHub Releases](https://github.com/dipeshbabu/private-lab-bench/releases/tag/v0.1.0). CI tests Python 3.10, 3.11, and 3.12.

Create a virtual environment:

```sh
python -m venv .venv
```

Activate it with `source .venv/bin/activate` on macOS/Linux, or `.venv\Scripts\Activate.ps1` in Windows PowerShell. Then install:

```sh
python -m pip install private-lab-bench==0.1.0
plb --help
```

The longer command name, `privatelabbench`, works too. See the [installation guide](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/install.md) for optional dependencies and source installs, or open the [quickstart in Colab](https://colab.research.google.com/github/dipeshbabu/private-lab-bench/blob/v0.1.0/examples/notebooks/quickstart.ipynb).

## Run a first evaluation

Run a bundled synthetic example in a fresh directory and verify its shareable receipt:

```sh
mkdir plb-example
cd plb-example
plb list-packs
plb run-pack community-tabular-regression@1.0.0
plb verify reports/benchmark_packs/tabular_regression_receipt.shareable.json
```

For v0.1.0, keep this folder empty before running the pack: a same-named local CSV can override the bundled fixture. The pack includes predictions, evaluation settings, and an example disclosure policy. It runs from the installed package without a checkout or model download. Other packs cover molecular regression and protein binary classification. Pack and protocol versions are independent of the package release.

## Evaluate your predictions

Save a table like this as `predictions.csv`:

```csv
sample_id,target,prediction,site
s01,0.12,0.14,lab-a
s02,0.20,0.23,lab-a
s03,0.33,0.31,lab-b
s04,0.41,0.45,lab-b
```

```sh
plb evaluate predictions.csv --task-type regression --slice site
plb verify reports/evaluation/evaluation_receipt.json
```

This writes local reports and a receipt. The four rows illustrate the schema; the default bootstrap requires at least 20 observations, and slice metrics require at least five per group. Repeated patients, compounds, or batches need a declared [sampling design](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/sampling_design.md).

Binary classification and multiclass probability tables are also supported. Class order and probability meaning matter: use explicit labels when needed. The [prediction-table reference](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/prediction_tables.md) covers column bindings, missing values, and classification examples.

Save the settings for another run:

```sh
plb init predictions.csv --task-type regression --slice site --out evaluation.yaml
plb validate-config evaluation.yaml
plb run evaluation.yaml
```

Use a versioned [evaluation protocol](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/protocols.md) when collaborators need the same metrics, sampling rules, and decision criteria. Receipts bind its identity and digest.

## Compare models

Provide one prediction table per model, with identical sample IDs and targets:

```sh
plb compare model-a.csv model-b.csv --target target --task-type regression --metric rmse --practical-threshold 0.01
```

The comparison reports the paired improvement, bootstrap interval, and whether the evidence supports your practical threshold. Subgroup comparisons help locate the difference. See the [paired-comparison guide](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/paired_comparison.md) for noninferiority, sampling assumptions, and interval interpretation.

## Scientific workflows

| Evaluation needs | Guide |
| --- | --- |
| Check supported split, entity, or time-overlap rules | [Evaluation-design audits](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/evaluation_design.md) |
| Inspect cohort degradation and changing groups | [Reference/current diagnostics](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/degradation.md) |
| Apply explicit acceptance thresholds | [Quality gates](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/quality_gates.md) |
| Describe an evaluated model and compare evidence across labs | [External validation](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/external_validation.md) and [receipt aggregation](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/aggregation.md) |
| Follow the same model over time | [Longitudinal evaluation](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/trends.md) |
| Evaluate submissions against owner-held labels | [Hidden benchmarks](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/hidden_benchmarks.md) |
| Generate predictions from an approved local numeric model | [Trusted local scoring](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/trusted_scoring.md) |

The initial benchmark integrations reproduce pinned upstream scoring rules:

| Ecosystem | Initial coverage |
| --- | --- |
| [TDC ADMET](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/tdc_admet.md) | Caco2 and PGP tasks with official splits and MAE/AUROC checks |
| [Matbench](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/matbench.md) | Selected composition and structure tasks with official folds and aggregation |
| [ProteinGym](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/proteingym.md) | A pinned DMS substitution subset with assay Spearman and protein/function aggregation |

The [Caco2 case study](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/case_study.md) follows a model-selection decision through uncertainty, critical-group checks, approved export, and signature verification. It distinguishes the real public control from a synthetic measurement-shift proxy. Independent researcher onboarding trials remain pending.

## Receipts and sharing

| Artifact | Purpose |
| --- | --- |
| `<run>_receipt.json` | Local evidence, including paths, configuration, and exact results |
| `<run>_receipt.shareable.json` | Approved aggregate evidence for exchange |
| `<run>_receipt.md` | Human-readable receipt summary |

A reviewed release policy controls export. When export is blocked, the run keeps its local results and release audit and removes a previous shareable receipt. Bundled packs use policies for synthetic examples; private-data evaluations need their own review.

```sh
plb release-check local_receipt.json --policy release.yaml
plb verify receipt.shareable.json --trust-store trusted-labs.yaml --require-trusted-signer --json
```

Verification distinguishes artifact integrity from an authenticated signer statement. Execution and scientific validity require separate evidence. The [receipt trust guide](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/receipt_trust.md) covers signing and pinned keys.

Keeping rows local limits data movement, but aggregates can still disclose sensitive information. Empirical audits, disclosure policies, and heuristic metric perturbation address different questions. Metric perturbation, including the deprecated `dp` alias, provides no formal differential privacy guarantee. Read the [privacy guide](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/privacy.md) before sharing private results.

## Developing and contributing

```sh
git clone https://github.com/dipeshbabu/private-lab-bench.git
cd private-lab-bench
python -m pip install -e '.[dev,docs]' build twine
python -m pre_commit install
python -m pre_commit run --all-files
python -m pytest -q
python -m mkdocs build --strict
```

CI checks supported Python versions, package builds, installation outside the checkout, documentation, Docker, scientific adapters, and repository history. Read [CONTRIBUTING.md](https://github.com/dipeshbabu/private-lab-bench/blob/main/CONTRIBUTING.md) for extension boundaries and validation requirements.

Report bugs or propose tasks through [GitHub Issues](https://github.com/dipeshbabu/private-lab-bench/issues/new/choose). Use the process in [SECURITY.md](https://github.com/dipeshbabu/private-lab-bench/blob/main/SECURITY.md) for sensitive vulnerabilities. Contributions follow the [Code of Conduct](https://github.com/dipeshbabu/private-lab-bench/blob/main/CODE_OF_CONDUCT.md) and [governance guide](https://github.com/dipeshbabu/private-lab-bench/blob/main/GOVERNANCE.md).

## License and citation

PrivateLabBench uses the [MIT license](https://github.com/dipeshbabu/private-lab-bench/blob/main/LICENSE). Cite the release or commit you used with [CITATION.cff](https://github.com/dipeshbabu/private-lab-bench/blob/main/CITATION.cff).
