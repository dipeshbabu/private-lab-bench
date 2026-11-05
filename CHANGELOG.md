# Changelog

## Unreleased

### Added

- A self-contained, fully synthetic 160-specimen onboarding example that uses the published v0.1.4 APIs to compute paired uncertainty and show a prespecified instrument failure despite overall improvement.
- CI that runs this walkthrough against the actual PyPI wheel outside the checkout, with local-only and explicitly approved synthetic export paths.
- A nine-combination Linux/Windows/macOS core compatibility matrix covering Python 3.10–3.14 where declared, with separate clean wheel and source installs, pinned representative dependencies, and retained semantic smoke results.
- Cross-platform checks for Unicode paths and groups, line endings, paired uncertainty, receipt verification, argument/quality exit codes, hard links, and release-state preservation. Optional scientific extras and the Linux/gVisor runtime retain separate coverage.

### Changed

- Organize the README, landing page, quickstart, and version-pinned Colab notebook around trying a decision, evaluating private predictions, and sharing approved evidence. Independent researcher trials remain pending.
- Document exact tested and untested OS/Python combinations and add Python 3.13/3.14 classifiers after successful core verification, without narrowing runtime dependency bounds or adding an upper Python ceiling.

## v0.1.4 — 2026-11-05

### Fixed

- Correct membership-risk diagnostics for unequal member/nonmember counts and inverted loss separation; evaluate thresholds in O(n log n) time and reject misaligned or nonfinite inputs.
- Reject malformed privacy-risk policies and nonfinite or unrepresentable heuristic noise parameters before evaluation or sampling.
- Respect declared probability-column labels in multiclass metrics, including nonconsecutive and reordered classes.
- Reject inconsistent aggregate evidence and malformed minimum-client/sample policies instead of silently weakening release thresholds.
- Preserve inputs and release state when SDK or CLI report paths collide, including hard links and reserved ledger/lock filenames.
- Treat malformed non-ASCII integrity digests as invalid evidence instead of crashing report and manifest verification.

Upgrade from v0.1.3 to receive these correctness and input-safety fixes. Rerun affected multiclass evaluations and membership audits from the original predictions; the corrected audit can change risk scores and policy decisions.

## v0.1.3 — 2026-11-03

### Added

- Linux/gVisor execution for untrusted Python inference scripts with a reviewed immutable runtime image, denied network access, restricted mounts and outputs, resource limits, and actual adversarial CI checks. Predictions and provenance stay local.
- Expand pinned coverage to six TDC ADMET tasks, five Matbench tasks, and ten ProteinGym substitution assays, with new versioned protocols and actual upstream parity records.
- Optional OpenDP bounded-mean backend with upstream clipping, floating-point sensitivity bounds, Laplace sampling, and an explicit shared budget. Its release object excludes exact means and private inputs.

### Fixed

- Reject nonfinite privacy budgets and spends; remove absolute comparison slack that could exceed very small budgets.
- Account for exact binary privacy spends, conservatively round usage/remaining totals, reject invalid restored ledgers, and normalize large finite weights without overflow.
- Exclude exact means from reference release serialization, label seeded outputs as deterministic tests without a DP guarantee, and reject unrepresentable noise scales.
- Explain how to use `sandbox-score` when the trusted scorer rejects untrusted scripts.

### Changed

- Read the PyPI version badge from the project's JSON metadata to avoid stale version results from the dedicated badge endpoint.
- Refresh installation instructions, the notebook, roadmap, and verified example receipts for v0.1.3. Regenerate the signed public Caco2 artifacts under this version.

## v0.1.2 — 2026-11-03

### Fixed

- Reject report paths that would overwrite input CSVs or another report in the legacy evaluation commands, including hard-link aliases.
- Make config validation and execution resolve relative inputs with the same configuration-first rules.
- Reject overlapping target, prediction, and sample-ID columns in prediction-table and paired evaluation.
- Reject ambiguous slice labels instead of silently replacing one group's results with another's.
- Report invalid config-run input with a concise rejection and exit code 2, preserving the distinct exit code for failed design audits.

### Changed

- Raise Dependabot’s per-ecosystem PR limit to ten while retaining grouped updates and scientific compatibility exclusions.
- Refresh the release checklist, roadmap, and independent-trial navigation.
- Apply Ruff checks to the report modules and refresh the PyPI badge cache URL.

## v0.1.1 — 2026-11-03

### Fixed

- Relative evaluation inputs now prefer files beside their configuration. Bundled packs use their own fixtures even when the working directory contains a same-named CSV. Legacy checkout-relative paths remain supported as a fallback.
- Grant the metadata labeler the PR-label write permission required by GitHub, while keeping repository contents read-only and loading trusted default-branch code.

### Changed

- Refresh the README around the published package, working command sequences, scientific workflows, and receipt trust.
- Enforce Ruff lint/format and pre-commit checks locally and in CI; clean up the existing style/import baseline.
- Add weekly Dependabot updates for Python dependencies, Actions, Docker, and pre-commit hooks, with explicit scientific-compatibility exclusions.
- Label new issues and PRs automatically using trusted default-branch code and metadata, including fork PRs.
- Create GitHub Releases automatically after successful PyPI publishing, attaching the published distributions and SHA-256 checksums.

Upgrade from v0.1.0 to receive the input-resolution correction.

## v0.1.0 — 2026-11-03

First community release of PrivateLabBench: local scientific evaluation with reviewed, shareable aggregate evidence.

### Added

- Prediction-table CLI, bundled synthetic benchmark packs, and extensible task plugins.
- Versioned evaluation protocols, uncertainty with declared sampling units, paired model comparison, scoped design audits, and distribution-change diagnostics.
- Model-quality gates, external-validation profiles, reviewed local numeric scoring, cross-site aggregation, hidden benchmarks, and longitudinal receipt analysis.
- Pinned TDC ADMET, Matbench, and ProteinGym integrations with real upstream parity checks.
- Explicit local/shareable boundaries, fail-closed release policies, and offline Ed25519 signer verification with limited-evidence trust statements.
- A reproducible public Caco2 case with an explicitly synthetic measurement-shift proxy. Independent researcher trials remain pending.
- Python 3.10–3.12 CI, wheel/source builds, clean-wheel checks, documentation builds, Docker checks, and full-history audit gates.

### Fixed

- Paired comparisons reject different targets and preserve numeric-looking class, slice, and cluster identifiers instead of treating them as approximately equal numbers.
- Two-column probability tables now produce a defined macro one-vs-rest AUC when both classes are present, including bootstrap intervals.
- Evaluation, comparison, aggregation, signing, and quality-gate output checks preserve input data, definitions, policies, trust stores, and signing keys before removing stale artifacts or writing reports.

### Changed

- `task:` is now the preferred config key; legacy `workflow:` remains supported;
- runner dispatch is registry-based;
- task plugins can be discovered through `privatelabbench.tasks` entry points;
- generic extension protocols no longer assume molecular datasets;
- a non-molecular `tabular` task and demo were added;
- CLI now focuses on local evaluation, comparison, validation, task discovery, and artifact verification.

The approved public-release history audit and author-email cleanup are complete. Earlier development numbering is superseded by this fresh v0.1.0 release; independently versioned protocols, schemas, benchmarks, and upstream dependencies retain their own identifiers.
