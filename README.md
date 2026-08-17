# PrivateLabBench

**Local-first evaluation for scientific machine learning on private data.**

PrivateLabBench helps researchers and scientific ML teams evaluate models on data that cannot leave their environment, then produce reproducible evaluation artifacts that can be inspected, verified, and selectively shared without sharing the underlying dataset.

> **Benchmark locally. Share evaluation artifacts, not raw data.**

PrivateLabBench is an open-source evaluation framework, not a hosted benchmark requirement. The core evaluation path runs locally and does not require a dashboard or external service.

## Why PrivateLabBench?

Scientific models are often evaluated on public benchmark datasets even though the distributions that matter in practice are private: internal assays, lab batches, partner datasets, site-specific measurements, unpublished experiments, or restricted research data.

That creates a recurring problem:

- a model can look strong on a public benchmark but fail on a private distribution;
- collaborators may need evidence about model performance without receiving the dataset;
- evaluation results need enough provenance to be reproduced and audited later;
- aggregate reports can themselves leak information and should be treated as release artifacts;
- evaluation should work with models that cannot be moved into a central benchmark server.

PrivateLabBench is designed around that boundary.

## What it does today

The current implementation includes:

- local evaluation of externally generated prediction CSVs;
- molecular property regression/classification workflows;
- multi-lab directory evaluation with aggregate reporting;
- regression metrics: MAE, RMSE, R²;
- classification metrics: accuracy, F1, AUROC;
- error-slice summaries;
- baseline model comparison;
- local membership-inference risk scoring;
- experimental DP-style metric perturbation;
- configurable release/privacy gates;
- Markdown and JSON reports;
- run manifests binding configs, reports, audit logs, and artifact hashes;
- optional signatures and runner attestation metadata;
- Dockerized local execution;
- an optional API/dashboard layer for teams that want a service interface.

The project is currently being refactored toward a domain-independent task/plugin architecture. See #11 for the community-release roadmap.

## What PrivateLabBench is not

PrivateLabBench is **not** intended to become:

- a central repository for every scientific dataset;
- a federated-training framework;
- a generic experiment tracker;
- an ELN/LIMS;
- a requirement to upload private data to a hosted service.

The focus is narrower: **standardized, reproducible evaluation of scientific models when the evaluation distribution is local or private.**

## Quickstart

PrivateLabBench is not yet published as a stable PyPI release. For now, install from source:

```bash
git clone https://github.com/dipeshbabu/private-lab-bench.git
cd private-lab-bench
pip install -e .
```

Run the included prediction example:

```bash
privatelabbench eval-predictions examples/predictions_demo.csv \
  --target label \
  --prediction-column pred \
  --report reports/prediction_eval_report.md \
  --json-report reports/prediction_eval_report.json
```

Or run the config-driven workflow:

```bash
privatelabbench run configs/prediction_eval.yaml
```

Validate a config before running it:

```bash
privatelabbench validate-config configs/prediction_eval.yaml
```

A config-driven run produces local reports plus a run manifest that binds the evaluation configuration and generated artifacts.

Verify a manifest:

```bash
privatelabbench verify-manifest reports/kinase_prediction_manifest.json
```

## Bring your own predictions

The lowest-friction workflow is to evaluate predictions your model already generated.

Current example format:

```csv
smiles,label,pred
CCO,0.12,0.14
CCN,0.20,0.23
c1ccccc1,0.74,0.71
```

Run:

```bash
privatelabbench eval-predictions predictions.csv \
  --target label \
  --prediction-column pred
```

This means PrivateLabBench does not need your model code. The model runs in your environment; PrivateLabBench evaluates its outputs locally.

The community roadmap is moving this toward a domain-independent prediction-table schema with stable sample IDs and optional metadata columns for slices such as site, batch, target family, assay, group, or time.

## Config-driven evaluation

Example:

```yaml
project: kinase-prediction-demo
workflow: predictions

benchmark:
  id: kinase-private-prediction
  version: "2026.05"
  suite: molecular-property
  domain: molecules

input:
  path: examples/predictions_demo.csv
  target_column: label
  prediction_column: pred
  task_type: regression

privacy:
  mode: none
  seed: 13

report:
  markdown: reports/kinase_prediction_eval.md
  json: reports/kinase_prediction_eval.json
  manifest: reports/kinase_prediction_manifest.json
```

Current workflows:

```text
predictions  evaluate externally generated predictions locally
molecules    train/evaluate the built-in molecule baseline
federated    evaluate multiple local lab CSVs and aggregate reports
```

## Molecular evaluation

The default lightweight adapter uses hashed SMILES fingerprints and a random forest baseline.

```bash
privatelabbench eval-molecules examples/molecules_demo.csv \
  --target label
```

Optional RDKit support:

```bash
pip install -e '.[rdkit]'
```

Then use the RDKit config:

```bash
privatelabbench run configs/molecule_eval_rdkit.yaml
```

See [`docs/ADAPTERS.md`](docs/ADAPTERS.md) for the current adapter layer and planned refactor.

## Multi-lab evaluation

The current federated-style workflow evaluates multiple local CSVs and produces per-client and aggregate summaries:

```bash
privatelabbench eval-federated examples/labs \
  --target label
```

This is evaluation/aggregation infrastructure, not federated model training.

## Privacy tooling

PrivateLabBench contains two different kinds of privacy-related functionality and they should not be confused.

### Privacy auditing

If a prediction export includes train/member vs test/nonmember information, PrivateLabBench can run a simple loss-threshold membership-inference baseline and report aggregate attack statistics.

This is a **privacy audit signal**, not a proof of privacy.

### Metric perturbation

The current `--privacy dp` mode applies Laplace noise to reported metrics using configured epsilon and sensitivity values.

This is currently best understood as **experimental DP-style metric perturbation**. The framework does not yet establish metric-specific global sensitivity and composition/accounting for arbitrary released metric sets, so the current implementation should **not** be interpreted as a general formal differential-privacy guarantee.

Formal privacy mechanisms/accounting are part of the open-source roadmap in #4.

## Reproducible artifacts

Config-driven evaluations generate artifacts that can include:

- Markdown report;
- JSON report;
- config snapshot;
- audit log;
- benchmark/run identity metadata;
- artifact hashes;
- run manifest;
- optional integrity signatures.

The project is moving toward a stable, versioned **evaluation receipt** schema (#6) that separates local/private fields from explicitly shareable aggregate fields.

## Model comparison

Run multiple configs and generate one comparison report:

```bash
privatelabbench compare \
  configs/prediction_eval.yaml \
  configs/molecule_eval.yaml \
  --report reports/model_comparison.md \
  --json-report reports/model_comparison.json
```

## Optional API and dashboard

PrivateLabBench also contains a FastAPI service and a dashboard for sanitized evaluation metadata. These are optional layers and are not required for local evaluation.

Install API dependencies:

```bash
pip install -e '.[api]'
```

Local API:

```bash
privatelabbench serve --host 127.0.0.1 --port 8000
```

Dashboard/API deployment documentation remains under `docs/`, but the community refactor is intentionally moving service operations away from the core first-use path. See #5.

## Project direction

The community release is organized around four priorities:

1. **Domain-independent evaluation core** — tasks, adapters, metrics, slices, privacy audits, and artifacts should be extensible without changing central dispatch code.
2. **Bring-your-own predictions** — any scientific model should be evaluable from a simple local prediction table.
3. **Evaluation receipts** — results should have stable, verifiable, versioned artifacts that remain useful without a hosted service.
4. **Community benchmark packs** — a small number of high-quality public examples should demonstrate how the same protocol works when the real evaluation data is private.

See the full roadmap in #11.

## Contributing

Contributions are welcome. Good areas include:

- scientific task/dataset adapters;
- evaluation metrics;
- calibration and uncertainty evaluation;
- metadata/error slices;
- privacy attacks and auditing methods;
- formal privacy mechanisms;
- report/receipt schemas;
- tests and documentation.

Development setup:

```bash
git clone https://github.com/dipeshbabu/private-lab-bench.git
cd private-lab-bench
pip install -e .
pip install pytest
pytest -q
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for contribution guidelines. The contributor surface itself is being expanded in #8.

## Design principles

- **Local first:** raw scientific samples should stay in the environment the user controls unless they explicitly choose otherwise.
- **Model agnostic:** evaluation should not require ownership of the model implementation.
- **Reproducible:** every result should be traceable to a task/config/version and generated artifacts.
- **Explicit sharing boundaries:** local/private outputs and shareable aggregate outputs should be distinguishable.
- **Extensible:** adding a scientific task or metric should not require redesigning the core runner.
- **Honest privacy claims:** heuristic privacy audits, metric perturbation, and formal privacy guarantees must remain clearly separated.

## License

PrivateLabBench is released under the MIT License. See [`LICENSE`](LICENSE).
