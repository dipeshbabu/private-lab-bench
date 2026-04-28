# Changelog

## 0.2.0 - Multi-client private evaluation

### Added

- Added `eval-federated` CLI command for directory-based multi-client evaluation.
- Added federated evaluator utilities for discovering client CSVs and evaluating each lab independently.
- Added weighted aggregation of clean and privacy-preserving reported metrics.
- Added aggregate dataset-shift summaries.
- Added example lab datasets under `examples/labs/`.
- Added federated Markdown report export.
- Added federated CLI smoke test to CI.
- Added federated evaluation tests.

### Notes

This is still a simulated local multi-client workflow. It does not yet implement networked secure aggregation or federated training. The value is that each client can be evaluated independently and only metrics/summaries are aggregated.

## 0.1.0 - Initial PrivateLabBench MVP

### Added

- Reframed project as PrivateLabBench: local-first private evaluation for scientific AI models.
- Added installable Python package with `privatelabbench` CLI.
- Added molecule CSV evaluation command: `eval-molecules`.
- Added hashed SMILES fingerprint baseline.
- Added RandomForest regression/classification baseline.
- Added regression metrics: MAE, RMSE, R2.
- Added classification metrics: accuracy, F1, AUROC.
- Added DP-style local metric perturbation.
- Added dataset shift summary.
- Added Markdown report export.
- Added demo molecule dataset.
- Added tests and CI workflow.

### Notes

This release is intentionally narrow. It is not yet a federated learning system or a hosted product. It is the first local runner skeleton for secure scientific model evaluation.
