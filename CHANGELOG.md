# Changelog

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
