# PrivateLabBench Roadmap

PrivateLabBench is transitioning into a community-first, local evaluation framework for scientific machine learning on private data.

The roadmap is organized around one principle:

> **Benchmark locally. Share reproducible evaluation artifacts, not raw data.**

The current repository already contains local evaluation, molecular baselines, multi-lab aggregation, privacy-risk tooling, signed manifests, an API, and a dashboard. The next phase is not to add more product infrastructure. It is to make the core smaller, domain-independent, easier to extend, and easier for researchers to use.

The live implementation tracker is GitHub issue #11.

## What is already implemented

### Local evaluation

- prediction CSV evaluation;
- molecular regression/classification baselines;
- config-driven local runs;
- Markdown and JSON reports;
- model comparison;
- error-slice summaries;
- multi-lab directory evaluation and aggregate reports.

### Reproducibility and integrity

- config snapshots;
- audit logs;
- report hashing;
- optional HMAC signatures;
- run manifests binding configs/reports/audit artifacts;
- runner identity/attestation metadata.

### Privacy-related tooling

- simple loss-threshold membership-inference risk scoring;
- experimental DP-style metric perturbation;
- privacy-risk release gates;
- aggregate release guards.

### Optional service infrastructure

- local FastAPI service;
- dashboard API/UI;
- sanitized sync/export;
- SQLite/PostgreSQL storage;
- signed runner sync;
- organization-scoped keys;
- deployment/audit/backup utilities.

These service features remain useful, but they are no longer the center of the open-source roadmap.

---

## Phase 0 — Public-release safety

Tracked by #9.

Before repository visibility changes:

- scan the full Git history for secrets/sensitive material;
- verify examples are safe to publish;
- review licenses and dependencies;
- rotate any credential that may ever have been committed;
- verify history after any cleanup/rewrite.

**The repository should remain private until this phase is complete.**

---

## Phase 1 — Domain-independent evaluation core

Tracked primarily by #1, #2, #4, and #6.

### 1. Task/plugin registry

Replace hard-coded workflow dispatch and molecule-specific generic interfaces with extensible contracts for:

- tasks;
- dataset adapters;
- prediction adapters;
- model adapters;
- metrics;
- slices;
- privacy audits;
- artifact writers.

A scientific domain should be addable without editing central runner logic.

### 2. Universal prediction-table path

Make bring-your-own-predictions the first-class interface.

Target base schema:

```text
sample_id,target,prediction
```

with optional metadata columns for domain-specific slicing.

The initial implementation should support:

- regression;
- binary classification;
- multiclass classification;
- stable sample IDs;
- arbitrary metadata/group columns;
- good schema-validation errors.

### 3. Evaluation receipt

Define a stable, versioned JSON artifact containing:

- task/benchmark identity;
- run identity;
- metric results;
- slices;
- privacy audits;
- provenance/config hashes;
- environment/runner version;
- artifact hashes;
- optional signatures/attestations;
- explicit local/private vs shareable fields.

This receipt must remain useful without a dashboard.

### 4. Privacy rigor

Clearly separate:

- privacy attacks/audits;
- heuristic/experimental release perturbation;
- formal privacy mechanisms.

The current Laplace metric-noise path should remain explicitly experimental until metric-specific sensitivity/bounds and composition/accounting are implemented.

---

## Phase 2 — Researcher-first usability

Tracked by #3, #5, and #10.

### Community positioning

Replace customer/buyer/pilot terminology with research/community language across public-facing docs and examples.

### Smaller CLI

Move toward a compact conceptual surface such as:

```bash
plb list
plb run benchmark.yaml
plb compare run-a.json run-b.json
plb verify receipt.json
```

Dashboard/server operations should become an optional command group or package rather than top-level first-use commands.

### Package installation and docs

Target:

```bash
pip install private-lab-bench
```

Add:

- PyPI releases;
- documentation site;
- 5-minute quickstart;
- one notebook/Colab example;
- release automation;
- troubleshooting for common scientific Python/RDKit issues.

---

## Phase 3 — Seed community evaluation packs

Tracked by #7.

Start with a small number of strong packs rather than many shallow integrations.

Recommended initial set:

1. **Molecules** — preserve/improve the current molecular evaluation path.
2. **Generic tabular science** — regression/classification with metadata slicing.
3. **One second scientific domain** — proteins or materials, selected for a clean public-data demonstration.

Each pack should include:

- versioned task IDs;
- a public/synthetic demo dataset or documented fetch path;
- baseline prediction files;
- expected evaluation receipts for regression testing;
- extension/contribution documentation.

PrivateLabBench should use public datasets to demonstrate workflows, not attempt to become a comprehensive scientific dataset hub.

---

## Phase 4 — Community contribution surface

Tracked by #8.

Add:

- expanded contributor guide;
- architecture/plugin authoring docs;
- `CODE_OF_CONDUCT.md`;
- `SECURITY.md`;
- `CITATION.cff`;
- issue/PR templates;
- curated labels and `good first issue` tasks;
- governance/maintainer expectations;
- optional GitHub Discussions.

Target contributor journey:

```text
find task
  ↓
install dev environment
  ↓
run tests
  ↓
add task / metric / slice / privacy audit
  ↓
open PR
```

A contributor should not need dashboard, PostgreSQL, SSO, or deployment knowledge to extend the evaluation core.

---

## Research directions after the community core stabilizes

Once the core abstraction and artifact schema are stable, useful directions include:

- calibration and uncertainty evaluation;
- stronger membership-inference attacks;
- property-inference/privacy attacks;
- formal DP mechanisms/accounting;
- distribution-shift and subgroup diagnostics;
- cross-site reproducibility analysis;
- benchmark/result artifact interoperability;
- proteins and protein engineering;
- microscopy/scientific vision;
- materials property prediction;
- reaction/yield models;
- lab automation and robotic experiment logs.

The order matters: these should be implemented as extensions of the same stable task/evaluation protocol rather than as new special-case workflows.

---

## Community-release bar

Before broadly announcing the project, aim for:

- [ ] public-release history/security audit complete;
- [ ] community-first README and scope;
- [ ] domain-independent task/plugin API;
- [ ] bring-your-own-predictions quickstart;
- [ ] stable evaluation receipt schema;
- [ ] privacy claims accurately scoped;
- [ ] normal package installation;
- [ ] documentation site + notebook;
- [ ] at least two meaningful benchmark packs;
- [ ] contribution templates and good-first-issue surface;
- [ ] CI green across supported Python versions.

## Long-term identity

PrivateLabBench should become a reusable evaluation protocol and extensible harness for scientific models evaluated on private/local distributions.

It should remain useful whether the user is an academic lab, open-source researcher, biotech team, or another organization with restricted evaluation data—and it should not require any of them to adopt a hosted service to use the core framework.
