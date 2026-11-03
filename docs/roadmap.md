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
- Synthetic molecule, tabular, and protein packs, plus pinned TDC ADMET,
  Matbench, and ProteinGym integrations checked against upstream implementations.
- Bounded-query privacy reference mechanisms and sequential budget accounting.
  These remain separate from privacy attacks and experimental metric noise.
- PyPI and GitHub releases, a documentation site, a checkout-free quickstart,
  a Colab notebook, Ruff/pre-commit checks, and dependency/label automation.

See the [changelog](https://github.com/dipeshbabu/private-lab-bench/blob/main/CHANGELOG.md)
for version history and [project scope](project_scope.md) for the limits of these
claims. Receipt signatures authenticate statements; they do not independently
verify model execution or scientific validity.

## Next implementation work

The following extensions are approved for development after the v0.1.2 patch:

- **Sandboxed execution of untrusted models:** a separate executor with enforced
  filesystem, egress, resource, and output restrictions, adversarial runtime
  checks, and no fallback to the trusted in-process scorer.
- **Broader benchmark coverage:** additional pinned tasks and assays, with
  explicit licenses, split definitions, metrics, and actual upstream parity.
- **A vetted differential-privacy backend:** optional OpenDP measurements for
  supported bounded queries, with explicit adjacency, sensitivity, and budget
  composition. Adding noise to arbitrary metrics is not sufficient.

These are development commitments, not features of v0.1.2. Their documentation
and release notes will describe the tested scope when they ship.

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
