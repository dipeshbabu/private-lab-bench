---
icon: material/clipboard-text-outline
---

# Caco2 model-selection case: analysis plan

This plan fixes the new proxy analysis before its execution. Public benchmark compatibility and the reference forest's public test score are already known from #36; this is not a blind prospective model competition or a preregistered clinical study.

The scientific task is Caco2_Wang regression under the pinned TDC ADMET snapshot `admet-4426004-bd0005246cb6`, using its official MAE definition and fixed scaffold test set. The objective is to decide whether a candidate that improves on a training-mean baseline also meets absolute and critical-group requirements under a controlled measurement shift.

## Frozen model and data choices

- Reference environment: Python 3.11, PyTDC 0.4.1, NumPy 1.26.4, Pandas 2.2.3, scikit-learn 1.9.1, RDKit-pypi 2022.9.5; use the constraints shipped with the walkthrough.
- Training: the official seed-1 default scaffold training partition only. Its validation partition is not used to fit or tune either model.
- Candidate: Morgan fingerprints, radius 2, 2,048 bits, bond types enabled, chirality disabled; random forest with 128 trees, minimum leaf size 2, square-root feature sampling, random state 1, and one CPU worker.
- Baseline: the training-target mean from the exact same training records.
- Public parity control: evaluate the full original official test set and compare fixed predictions against TDC's raw evaluator at absolute tolerance `1e-12`.
- New proxy: reuse the public held-out compounds and original record IDs. Add **+0.8 in the upstream target scale** to targets whose RDKit MolLogP is at least 3.0. Keep other targets unchanged. This is an invented measurement-shift stress test, not measured private lab data or an independent collection of new compounds.
- Critical partition: `regime=high-logp` versus `regime=other`, fixed by that descriptor threshold. Do not select cutoffs using model errors.

## Eligibility and audit scope

Use canonical molecular-connectivity SMILES with stereochemistry ignored, hashed with SHA-256, as the declared entity and resampling unit. Preserve repeated measurements and cluster them together. Exclude evaluation records whose connectivity graph occurs in the candidate's actual training records; this eligibility rule is based on training overlap, not model performance. Report total/eligible/excluded counts. The public parity control remains on the full official test set independently of proxy eligibility.

Audit complete sample IDs, exact connectivity-entity overlap, and the predeclared eligibility rule against the full actual training reference. Do not check noisy regression labels as if they were deterministic class labels. Passing supported checks does not prove independence, absence of near-neighbor/scaffold leakage, chronology validity, or representative sampling.

## Frozen inference and decision rules

- Primary metric: MAE, lower is better.
- Uncertainty: 1,000 cluster bootstrap resamples over connectivity units, seed 13, nominal 95% intervals, minimum 20 independent units. Treat independence between nonidentical connectivity graphs as an assumption; structural similarity can still violate it.
- Paired comparison: candidate versus mean on identical eligible IDs/targets, practical improvement threshold 0.02. Use paired cluster bootstrap intervals and no randomization permutations; do not silently assert exchangeability.
- Critical slices: report both complete partition cells; an underpowered interval remains unavailable. Do not tune groups to obtain significance.
- Absolute quality requirements: candidate MAE at most 0.6, its overall CI upper bound at most 0.7, and high-logP-group MAE at most 0.7. Report the actual pass/fail/investigate outcome, including unfavorable results.
- Reference/current diagnostics: original public held-out labels versus the proxy labels. These reuse compounds and IDs, so `independent_cohorts` is false. Do not invent independent-cohort confidence intervals for that change.
- Model selection and deployment acceptability are separate questions. Relative improvement does not waive an absolute/critical-group failure.

## Release and verification

Keep raw SMILES, row IDs, targets, predictions, model parameters, paths, and full audits local. Publish only explicitly approved aggregate receipts/comparison summaries, an approved complete critical partition, and a public example trust store. Require complete supported design-audit evidence for publication. The empirical-membership-attack requirement is disabled explicitly for this public/synthetic demonstration; no formal differential privacy claim is made.

Freeze data-only numeric model snapshots and record their actual digests. Demonstrate Ed25519 verification with a local example issuer and a pinned public key. A signature authenticates that example issuer's statement; it does not independently establish execution, dataset truth, or scientific validity. The private signing key stays in the local output directory.

## Independent trials remain a separate requirement

Run at least three voluntary onboarding trials with researchers who did not build the package. Collect only redacted setup friction, elapsed time, confusing outputs, verification misunderstandings, and decision usefulness. Do not request private datasets, contact details, telemetry, or training artifacts. CI runs and the author's own environments do not count as independent trials. Findings and at least two changes responding to observed friction cannot be claimed until those trials actually happen.
