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

## v0.3: Secure benchmark reports

Goal: make outputs useful for model comparison and pilot conversations.

Planned features:

- JSON and Markdown benchmark reports
- model cards for evaluated baselines
- privacy risk section
- per-client heterogeneity summary
- reproducible run metadata
- stable report schema for a hosted dashboard

## v0.4: Scientific model adapters

Goal: move beyond toy baselines.

Planned features:

- optional RDKit Morgan fingerprints
- ChemBERTa adapter
- simple graph neural network adapter
- support for external prediction files

## v0.5: Privacy and attack evaluation

Goal: quantify what is leaked by evaluation artifacts.

Planned features:

- membership inference risk scoring
- property inference risk scoring
- DP budget reporting
- privacy/utility tradeoff plots

## v0.6: Local runner + hosted dashboard

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
