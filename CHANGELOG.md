# Changelog

## Unreleased - Production deployment hardening

### Added

- Added `docker-compose.prod.yml` for production-style dashboard deployment and optional local API service.
- Added `.env.example` with required dashboard/API environment variables.
- Added production runtime checks for required API keys and persistent storage paths.
- Added production deployment runbook under `docs/production_deployment.md`.
- Added CI validation for the production Docker Compose configuration.

### Changed

- Made the Docker healthcheck port configurable so dashboard and API containers can both report healthy.

## 0.9.0 - Sanitized hosted dashboard sync

### Added

- Added hosted dashboard API under `privatelabbench.dashboard.api`.
- Added SQLite dashboard store for sanitized run metadata and audit events.
- Added `privatelabbench serve-dashboard` for local dashboard API pilots.
- Added `privatelabbench export-sanitized` for dashboard-safe payload generation.
- Added `privatelabbench sync-dashboard` for sending sanitized metrics to a dashboard endpoint.
- Added dashboard API-key authentication via `PRIVATELABBENCH_DASHBOARD_API_KEY`.
- Added artifact hash metadata for synced reports without uploading raw report contents.
- Added tests for sanitization and dashboard-store roundtrips.

### Notes

This release turns the product into a clearer local-runner plus hosted-dashboard architecture. Labs can keep raw datasets, predictions, SMILES strings, and local reports on their own machine while sharing only sanitized aggregate metadata with a central dashboard.

## 0.6.0 - Signed reports and audit metadata

### Added

- Added canonical JSON report hashing with SHA256.
- Added optional HMAC-SHA256 report signing.
- Added `privatelabbench verify-report` CLI command.
- Added config snapshots to config-driven JSON reports.
- Added local JSONL audit logs for config runner executions.
- Added report integrity tests covering valid, signed, and tampered reports.
- Added CI smoke tests for report verification and signed report verification.
- Added report integrity documentation under `docs/report_integrity.md`.
- Bumped package version to `0.6.0`.

### Notes

This release makes evaluation artifacts more suitable for pilots. A customer can run a local evaluation, produce a JSON report with integrity metadata, optionally sign it using a local secret, and verify that the report was not changed before sharing it internally.

## 0.5.0 - Dockerized local runner and customer pilot docs

### Added

- Added Dockerfile for local-only customer runner execution.
- Added `.dockerignore` for cleaner image builds.
- Added Docker CI job with image build and config-runner smoke test.
- Added customer onboarding guide under `docs/customer_onboarding.md`.
- Added customer pilot checklist under `docs/pilot_checklist.md`.
- Updated README with Docker workflow and pilot documentation links.
- Bumped package version to `0.5.0`.
- Added `PyYAML` to package dependencies.

### Notes

This release makes PrivateLabBench easier to run in a customer pilot. A lab can now build a container, mount its local data directory, run a YAML evaluation config, and export reports without changing the Python environment on its host machine.

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
- Added federated evaluation tests.
- Added federated CLI smoke test to CI.

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
