# Changelog

## Unreleased — Community refactor

PrivateLabBench is being refactored around an open-source, local-first scientific evaluation workflow.

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

Historical pre-community implementation details remain available in Git history until the public-release history audit is complete.
