# Changelog

## 0.4.0 - Config-based local runner

### Added

- Added `privatelabbench run <config.yaml>` for repeatable local evaluation workflows.
- Added YAML config loader and validation.
- Added config runner support for prediction, molecule, and federated workflows.
- Added example configs under `configs/`.
- Added JSON export for molecule and federated config runs.
- Added config runner tests.
- Added config runner CI smoke test.
- Added PyYAML dependency.

### Notes

This release makes PrivateLabBench feel closer to a customer-deployable local runner. A pilot user can now keep their evaluation settings in a YAML file and rerun the same private benchmark without remembering long CLI commands.

## 0.3.0 - Customer prediction evaluation and JSON reports

### Added

- Added `eval-predictions` CLI command for externally generated model predictions.
- Added prediction CSV evaluator for customer-owned models.
- Added prediction summary statistics.
- Added machine-readable JSON report writer with run metadata.
- Added Markdown prediction evaluation reports.
- Added prediction demo CSV under `examples/predictions_demo.csv`.
- Added prediction evaluation tests.
- Added prediction CLI smoke test to CI.

### Notes

This release makes the product easier to pilot because customers can evaluate their own model outputs without integrating model code into PrivateLabBench. They only need a local CSV containing the target column and prediction column.

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
