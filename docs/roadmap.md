# PrivateLabBench Roadmap

PrivateLabBench is becoming a community-first evaluation harness for scientific machine learning on private data.

> **Benchmark locally. Share reproducible evaluation artifacts, not raw data.**

## Phase 0 — Safe public release

Before changing repository visibility, scan the full Git history for credentials and sensitive material, verify example data and licenses, remove private/internal material, and rotate any credential that may ever have been committed.

## Phase 1 — Domain-independent core

### Task registry

Initial implementation includes stable task IDs, third-party discovery through `privatelabbench.tasks`, legacy `workflow:` compatibility, preferred `task:` configs, registry-based dispatch, and a non-molecular `tabular` task.

Next: task-owned config schemas, richer plugin metadata/versioning, and plugin compatibility tests.

### Extension protocols

Common protocols cover tasks, dataset adapters, model adapters, metrics, slices, privacy audits, and artifact writers.

Next: remove remaining molecule assumptions from multi-site evaluation.

### Prediction-table interface

Next: stable `sample_id,target,prediction` schema, multiclass classification, arbitrary metadata/group columns, first-class slices, and clearer validation errors.

## Phase 2 — Evaluation receipt

Define a stable versioned artifact containing task/benchmark identity, run ID, input schema summary, sample counts, metrics, uncertainty, slices, privacy audits, provenance/config hashes, runtime version, artifact hashes, optional signatures, and explicit local/private vs shareable fields.

## Phase 3 — Privacy rigor

Clearly separate privacy attacks/audits, experimental metric perturbation, and formal privacy mechanisms. Priorities include stronger attacks, bounded queries, metric-specific sensitivity, composition/accounting, and privacy/utility diagnostics.

## Phase 4 — Researcher usability

- PyPI releases;
- documentation site;
- 5-minute quickstart;
- notebook/Colab example;
- task/plugin authoring tutorial;
- improved errors;
- good-first-issue contribution surface.

## Phase 5 — Community task packs

Start with molecules, generic tabular science, and one additional scientific domain such as proteins or materials. Each pack should include versioned task IDs, public/synthetic demos, baseline predictions, known-good artifacts, and contribution docs.

## Research directions

Calibration and uncertainty, distribution shift, subgroup diagnostics, cross-site reproducibility, proteins, microscopy, materials, reactions, lab automation/robotics, and evaluation-artifact interoperability.
