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

Status: implemented.

- `privatelabbench run <config.yaml>`
- YAML config schema
- support for molecule, federated, and prediction workflows
- stable report output paths
- JSON reports for config-driven molecule, prediction, and federated runs
- example customer configs under `configs/`
- CI smoke test for the config runner

## v0.5: Dockerized local runner and onboarding

Status: implemented.

- Dockerfile for local-only execution
- `.dockerignore`
- Docker CI smoke test
- `docker run` examples for configs
- customer onboarding guide
- pilot checklist
- local data privacy checklist
- pilot success criteria template

## v0.6: Signed reports and audit metadata

Status: implemented.

- deterministic report hashing
- SHA256 digest in JSON report metadata
- optional HMAC report signature
- `privatelabbench verify-report` command
- config snapshot embedded in JSON reports
- basic audit event log for local runs

## v0.7: Scientific model adapters

Goal: move beyond toy baselines.

Status: partially implemented.

Implemented:

- optional RDKit Morgan fingerprints
- adapter interface for built-in and external evaluation paths
- model comparison reports across configs

Next adapter targets:

- ChemBERTa adapter
- simple graph neural network adapter
- support for external model endpoints

## v0.8: Privacy and attack evaluation

Goal: quantify what is leaked by evaluation artifacts.

Planned features:

- membership inference risk scoring
- property inference risk scoring
- DP budget reporting
- privacy/utility tradeoff plots

## v0.9: Local runner + hosted dashboard

Goal: make the workflow product-like while keeping raw data local.

Status: implemented for sanitized dashboard sync pilots.

- local runner agent
- hosted aggregate dashboard
- signed reports
- team/project organization
- sanitized export and sync commands
- private benchmark network prototype remains future work

## Long-term domains

After molecules, possible scientific domains include:

- protein binding and protein engineering
- microscopy image analysis
- materials property prediction
- reaction yield prediction
- lab automation and robotic experiment logs
