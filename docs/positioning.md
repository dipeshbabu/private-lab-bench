# PrivateLabBench Project Scope

PrivateLabBench is an open-source, local-first evaluation framework for scientific machine learning on private data.

## One-line description

Evaluate scientific ML models on data that cannot leave your environment, then generate reproducible evaluation artifacts that can be inspected, verified, and selectively shared without sharing the underlying dataset.

## Core idea

**Benchmark locally. Share evaluation artifacts, not raw data.**

Scientific evaluation distributions are often private or restricted: internal assays, unpublished experiments, lab/site batches, partner datasets, proprietary measurements, or other data that cannot be uploaded to a public benchmark service.

PrivateLabBench is intended to make those evaluations more standardized and reproducible.

## Primary users

The project is designed for:

- scientific ML researchers;
- computational biology/chemistry/materials researchers;
- research engineers evaluating external or internal models;
- labs collaborating across data-sharing boundaries;
- privacy and evaluation researchers building new auditing methods;
- open-source contributors adding scientific tasks, metrics, slices, or privacy methods.

The project should remain useful to commercial teams, but commercial deployment is not the organizing principle of the open-source core.

## First-class workflow

The lowest-friction workflow is **bring your own predictions**:

1. run a model in the environment where the data/model already live;
2. export predictions plus targets and optional metadata;
3. run PrivateLabBench locally;
4. compute metrics, slices, privacy audits, and provenance;
5. generate a reproducible evaluation artifact;
6. share only the artifact fields the user intends to release.

This avoids requiring PrivateLabBench to own or execute every scientific model implementation.

## North-star artifact

The long-term central output is a versioned **evaluation receipt**: a machine-readable, verifiable record of an evaluation run that includes task identity, metrics, slices, privacy/audit results, configuration/provenance, and artifact hashes while keeping raw private samples local.

A hosted dashboard may visualize these artifacts, but the artifact format must remain useful without any hosted service.

## Scope

PrivateLabBench should focus on:

- local/private evaluation;
- model-agnostic prediction evaluation;
- standardized scientific task definitions;
- metrics, calibration, uncertainty, and distribution slices;
- privacy-risk auditing;
- clearly scoped privacy-preserving release mechanisms;
- reproducible configs and run provenance;
- verifiable evaluation artifacts;
- multi-site/multi-lab aggregate evaluation;
- community-contributed benchmark/task packs.

## Non-goals

PrivateLabBench should not try to become:

- a dataset warehouse for all scientific ML;
- a generic model-training framework;
- a federated-training framework;
- an experiment tracker/ML platform;
- an ELN/LIMS;
- a mandatory hosted benchmark server;
- a private leaderboard network as the core product identity.

These adjacent workflows may integrate with PrivateLabBench, but they should not define the core abstraction.

## Architecture direction

The core should become domain-independent through registries/interfaces for:

- tasks;
- dataset/prediction adapters;
- model adapters where needed;
- metrics;
- slices;
- privacy audits;
- release mechanisms;
- artifact writers.

A new scientific domain should be addable without editing central runner dispatch code.

## Privacy language

PrivateLabBench must distinguish between:

1. **privacy auditing** — e.g. membership-inference attacks that estimate leakage risk;
2. **metric perturbation/release mechanisms** — transformations applied to reported results;
3. **formal privacy guarantees** — mechanisms with a well-defined threat model, sensitivity/bounds, and accounting.

The current Laplace metric-noise implementation is experimental DP-style perturbation and should not be presented as a general formal differential-privacy guarantee until the missing sensitivity/accounting requirements are addressed.

## Optional service layer

The existing API server, dashboard, PostgreSQL backend, signed sync, organization keys, deployment hardening, SSO proxy support, and operational utilities may remain available as optional infrastructure.

They should not be required to understand, install, run, extend, or cite the core evaluation framework.

## Community direction

The community release should optimize for:

- a 5–10 minute first evaluation;
- a small stable CLI;
- normal package installation;
- high-quality docs/examples;
- clear extension interfaces;
- task/metric/privacy contribution paths;
- public benchmark packs that demonstrate workflows without requiring private data;
- conservative scientific claims about privacy and evaluation guarantees.

The implementation roadmap is tracked in GitHub issue #11.
