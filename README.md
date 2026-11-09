<p align="center">
  <img src="https://raw.githubusercontent.com/dipeshbabu/private-lab-bench/main/docs/assets/logo.svg" alt="PrivateLabBench logo" width="96" height="96">
</p>

<h1 align="center">PrivateLabBench</h1>

<p align="center">
  Evaluate scientific models on private data, from your terminal.
</p>

<p align="center">
  <a href="https://pypi.org/project/private-lab-bench/"><img alt="PyPI version" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fpypi.org%2Fpypi%2Fprivate-lab-bench%2Fjson&amp;query=%24.info.version&amp;label=pypi&amp;prefix=v&amp;style=flat-square&amp;cacheSeconds=300"></a>
  <a href="https://github.com/dipeshbabu/private-lab-bench/actions/workflows/ci.yml"><img alt="Build" src="https://img.shields.io/github/actions/workflow/status/dipeshbabu/private-lab-bench/ci.yml?branch=main&label=build&style=flat-square"></a>
  <a href="https://dipeshbabu.github.io/private-lab-bench/support/"><img alt="Python 3.10 through 3.15; see tested support" src="https://img.shields.io/badge/python-3.10%E2%80%933.15-blue?style=flat-square"></a>
  <a href="https://github.com/dipeshbabu/private-lab-bench/blob/main/LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-green?style=flat-square"></a>
</p>

<p align="center">
  <a href="https://dipeshbabu.github.io/private-lab-bench/quickstart/">Quickstart</a> ·
  <a href="https://dipeshbabu.github.io/private-lab-bench/">Documentation</a> ·
  <a href="https://github.com/dipeshbabu/private-lab-bench/releases/tag/v0.1.6">v0.1.6 release</a> ·
  <a href="https://github.com/dipeshbabu/private-lab-bench/blob/main/CONTRIBUTING.md">Contributing</a>
</p>

---

PrivateLabBench is a local evaluation framework for scientific machine learning. Bring model predictions and a validation table to compare candidates, estimate uncertainty, and find failures across sites, assays, or other groups. Keep the underlying data in your environment and share approved aggregate receipts with collaborators.

Evaluation runs without an account, hosted service, or data upload. A receipt records the evaluation protocol, selected results, and the evidence available to verify them.

## Installation

The current release is **v0.1.6**, available on [PyPI](https://pypi.org/project/private-lab-bench/0.1.6/) and [GitHub Releases](https://github.com/dipeshbabu/private-lab-bench/releases/tag/v0.1.6). The core has clean-install checks on Linux for Python 3.10–3.15 and on Windows/macOS for 3.12 and 3.14. See the [tested-support matrix](https://dipeshbabu.github.io/private-lab-bench/support/) for exact scope and optional-integration limits.

This release includes the v0.1.4 correctness fixes for multiclass scoring, membership-risk diagnostics, privacy-policy validation, and input-safe report writing. Rerun affected evaluations from the original predictions when upgrading from earlier releases.

Create a virtual environment:

```sh
python -m venv .venv
```

Activate it with `source .venv/bin/activate` on macOS/Linux, or `.venv\Scripts\Activate.ps1` in Windows PowerShell. Then install:

```sh
python -m pip install private-lab-bench==0.1.6
plb --help
```

The longer command name, `privatelabbench`, works too. See the [installation guide](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/install.md) for optional dependencies and source installs, or open the [quickstart in Colab](https://colab.research.google.com/github/dipeshbabu/private-lab-bench/blob/main/examples/notebooks/quickstart.ipynb).

## 1. Try a scientific decision in five minutes

The candidate improves overall. Does it still fail on a required instrument?
Run this fully synthetic calibration example: 160 simulated specimens, two
instruments, a baseline, and acceptance thresholds fixed before evaluation.
No training or model download is needed.

In a fresh working directory, download the small example and run it:

```sh
python -c "from urllib.request import urlretrieve; urlretrieve('https://raw.githubusercontent.com/dipeshbabu/private-lab-bench/main/examples/first_run.py', 'first_run.py')"
python first_run.py --output-dir plb-demo
plb verify plb-demo/evaluation/evaluation_receipt.json
```

These commands work in PowerShell, bash, and zsh with the installed v0.1.6 package.
The observed result, rounded for display:

```text
Candidate MAE 0.272; baseline MAE 0.497 (lower is better).
Paired improvement 0.225; 95% CI [0.178, 0.267]; required improvement 0.05.
Instrument B MAE 0.797 exceeds the prespecified maximum 0.50.
Decision: REJECT for instrument B despite the overall improvement; quality gate FAIL.
```

The interval and subgroup checks are computed by the normal evaluation APIs.
Inspect `plb-demo/decision.json`, `plb-demo/paired.md`, and the local evaluation
receipt. This constructed example illustrates a decision; it supplies no evidence
about a real biological task or outside-researcher adoption. See the
[walkthrough](https://dipeshbabu.github.io/private-lab-bench/quickstart/) for
assumptions, optional synthetic export, troubleshooting, and the
[Colab notebook](https://colab.research.google.com/github/dipeshbabu/private-lab-bench/blob/main/examples/notebooks/quickstart.ipynb).

## 2. Evaluate your own predictions

Export a local CSV with stable `sample_id`, observed `target`, model `prediction`,
and optional group columns such as `instrument`. Then run:

```sh
plb evaluate YOUR.csv --task-type regression --slice instrument --output-dir YOUR_RESULTS
plb verify YOUR_RESULTS/evaluation_receipt.json
```

This keeps results local. The default confidence interval needs at least 20
observations; each evaluated group needs at least five. Repeated patients,
compounds, or batches need a declared
[sampling design](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/sampling_design.md).
Choose quality thresholds for your scientific use case before looking at results.

Binary classification and multiclass probability tables are also supported. Class order and probability meaning matter: use explicit labels when needed. The [prediction-table reference](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/prediction_tables.md) covers column bindings, missing values, and classification examples.

Save the settings for another run:

```sh
plb init predictions.csv --task-type regression --slice site --out evaluation.yaml
plb validate-config evaluation.yaml
plb run evaluation.yaml
```

Use a versioned [evaluation protocol](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/protocols.md) when collaborators need the same metrics, sampling rules, and decision criteria. Receipts bind its identity and digest.

### Compare models

Provide one prediction table per model, with identical sample IDs and targets:

```sh
plb compare model-a.csv model-b.csv --target target --task-type regression --metric rmse --practical-threshold 0.01
```

The comparison reports the paired improvement, bootstrap interval, and whether the evidence supports your practical threshold. Subgroup comparisons help locate the difference. See the [paired-comparison guide](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/paired_comparison.md) for noninferiority, sampling assumptions, and interval interpretation.

## 3. Share approved evidence

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
| Isolate an untrusted Python model on a Linux/gVisor host | [Sandboxed execution](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/sandbox.md) |
| Release a bounded mean with an explicit privacy budget | [Optional OpenDP backend](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/privacy.md#optional-opendp-backend) |

The development branch's benchmark integrations reproduce pinned upstream scoring rules:

| Ecosystem | Tested coverage |
| --- | --- |
| [TDC ADMET](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/tdc_admet.md) | Eight tasks covering permeability, absorption, transport, mutagenicity, cardiotoxicity, lipophilicity, and solubility; official splits and MAE/AUROC checks |
| [Matbench](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/matbench.md) | Seven composition/structure tasks with official folds, target units, and aggregation |
| [ProteinGym](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/proteingym.md) | Twelve pinned substitution assays with assay Spearman and protein/function aggregation |

Sandbox execution requires a reviewed local runtime image and gVisor; it rejects
missing isolation and keeps predictions private. The optional OpenDP backend
uses public bounds and fixed sample size, checks upstream privacy maps, and
requires a shared budget. Neither extension automatically authorizes disclosure
of model outputs or existing exact evaluation reports.

The development branch adds a [durable local privacy ledger](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/privacy.md#durable-local-accounting-unreleased)
for shared OpenDP accounting across worker processes and restarts. This API is
unreleased; v0.1.7 remains subject to the release prerequisites.

The [Caco2 case study](https://github.com/dipeshbabu/private-lab-bench/blob/main/docs/case_study.md) follows a model-selection decision through uncertainty, critical-group checks, approved export, and signature verification. It distinguishes the real public control from a synthetic measurement-shift proxy. Independent researcher onboarding trials remain pending.

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
