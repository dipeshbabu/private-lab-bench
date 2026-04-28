# PrivateLabBench Roadmap

PrivateLabBench is being built as secure evaluation infrastructure for scientific AI. The product wedge is private model evaluation before federated training.

## v0.1: Local private molecule evaluation

Status: implemented.

- Single local CSV runner
- Molecular property prediction baseline
- Local metrics
- DP-style reported metrics
- Markdown report
- CLI and tests

## v0.2: Multi-client private evaluation

Status: implemented.

- `eval-federated` command over a directory of lab CSVs
- per-client metrics
- aggregate metric report
- client distribution-shift summary
- weighted aggregation by sample count
- privacy-preserving aggregate report
- example multi-lab datasets and report

## v0.3: Customer prediction evaluation and JSON reports

Status: implemented.

- `eval-predictions` command for externally generated model outputs
- Markdown prediction reports
- JSON report schema with run metadata
- prediction summary statistics
- CI smoke test for prediction evaluation
- customer-friendly path for evaluating private model outputs

## v0.4: Config-based local runner

Goal: make the workflow product-like and repeatable.

Planned features:

- `privatelabbench run privatelabbench.yaml`
- YAML config schema
- support for molecule, federated, and prediction workflows
- stable output directory conventions
- reproducible run metadata
- example customer configs

## v0.5: Scientific model adapters

Goal: move beyond toy baselines.

Planned features:

- optional RDKit Morgan fingerprints
- ChemBERTa adapter
- simple graph neural network adapter
- support for external model endpoints

## v0.6: Privacy and attack evaluation

Goal: quantify what is leaked by evaluation artifacts.

Planned features:

- membership inference risk scoring
- property inference risk scoring
- DP budget reporting
- privacy/utility tradeoff plots

## v0.7: Local runner + hosted dashboard

Goal: make the workflow product-like while keeping raw data local.

Planned features:

- local runner agent
- hosted aggregate dashboard
- signed reports
- team/project organization
- private benchmark network prototype

## Long-term domains

After molecules, possible scientific domains include:

- protein binding and protein engineering
- microscopy image analysis
- materials property prediction
- reaction yield prediction
- lab automation and robotic experiment logs
