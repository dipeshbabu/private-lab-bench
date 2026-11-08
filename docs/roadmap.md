# Roadmap

PrivateLabBench evaluates scientific models where the data lives and produces
reviewed aggregate evidence. This page separates shipped capabilities from work
that still needs implementation or outside evidence.

## Available now

- A task registry and plugin entry points, prediction-table evaluation for
  regression and classification, metadata slices, and paired comparisons.
- Versioned protocols and receipts, declared sampling units, uncertainty,
  design audits, quality gates, and reference/current diagnostics.
- Explicit local and shareable outputs, fail-closed release policies, offline
  Ed25519 verification, cross-site receipt aggregation, and longitudinal trends.
- Reviewed numeric local model scoring and owner-controlled hidden benchmarks.
  The trusted scorer runs in process and provides no execution sandbox.
- A separate [Linux/gVisor executor](sandbox.md) for untrusted Python inference
  scripts, with restricted mounts, denied network access, resource and output
  limits, and adversarial runtime checks. Predictions remain local.
- Synthetic molecule, tabular, and protein packs, plus pinned TDC ADMET,
  Matbench, and ProteinGym integrations checked against upstream implementations:
  six ADMET tasks, five materials tasks, and ten DMS substitution assays.
- Bounded-query privacy reference mechanisms and sequential budget accounting.
  These remain separate from privacy attacks and experimental metric noise.
- An optional [OpenDP bounded-mean backend](privacy.md#optional-opendp-backend)
  using upstream transformations, numerical privacy maps, and Laplace sampling,
  with public bounds/size and an explicit shared budget.
- PyPI and GitHub releases, a documentation site, a checkout-free quickstart,
  a Colab notebook, Ruff/pre-commit checks, and dependency/label automation.

See the [changelog](https://github.com/dipeshbabu/private-lab-bench/blob/main/CHANGELOG.md)
for version history and [project scope](project_scope.md) for the limits of these
claims. Receipt signatures authenticate statements; they do not independently
verify model execution or scientific validity.

## Extension boundaries

The three extensions added in v0.1.3 have explicit limits. The sandbox supports
CPU Python scripts in an operator-reviewed image. The unreleased model-package
format adds bounded, multi-file CPU models; participant images and GPU execution
remain unsupported. Its controls and tests do not constitute an
independent security audit. OpenDP currently supports bounded means with fixed
public size and row-level replace-one adjacency; the application must maintain
accounting across processes and restarts. Its upstream `contrib` status and
privacy assumptions are documented. Benchmark coverage remains a tested subset
of each upstream suite.

## Independent researcher evidence

The [public Caco2 case](case_study.md) is reproducible, but independent onboarding
trials remain **0 of at least 3**. Issues
[#40](https://github.com/dipeshbabu/private-lab-bench/issues/40) and
[#47](https://github.com/dipeshbabu/private-lab-bench/issues/47) stay open until
voluntary trials, redacted findings, and at least two changes based on observed
friction are documented. See the [trial guide](case_study/trial_guide.md) and
[findings](case_study/findings.md). Automated runs do not count as trials.

## Further work

Task-owned configuration schemas, richer plugin compatibility metadata, and
additional scientific domains remain candidates for later releases. The legacy
raw-input multi-site workflow is molecule-specific; general cross-site evidence
currently uses aggregate receipts.
