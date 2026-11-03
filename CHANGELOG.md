# Changelog

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
