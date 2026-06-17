# PrivateLabBench

PrivateLabBench is private scientific AI evaluation and trust infrastructure.

It helps biotech, pharma, CRO, and scientific ML teams prove whether an AI model works on proprietary lab data without exposing raw rows, model code, or sensitive prediction outputs. Teams run evaluations locally, produce signed evidence packages, quantify privacy risk, and sync only sanitized evaluation metadata to a hosted dashboard.

The initial product wedge is private evaluation of molecular property, ADMET, assay activity, and other scientific prediction models from customer-owned prediction CSVs. The larger product is the trust layer for scientific AI model claims: before a model is bought, licensed, published, deployed, or used in a program decision, PrivateLabBench can generate reproducible evidence on private data.

## Product thesis

Scientific AI buyers do not just need another model or benchmark. They need defensible answers to these questions:

- Does this model work on our private assay, chemistry, biology, or lab-batch distribution?
- Did performance hold across sites, batches, targets, partners, or time periods?
- Can we share evidence with leadership, legal, vendors, partners, or auditors without exposing raw data?
- Can a model vendor prove a claim without receiving the customer's proprietary dataset?
- Can every reported result be reproduced, verified, and traced back to the exact config and artifacts?

PrivateLabBench turns local private evaluations into signed, sanitized trust artifacts.

## Current scope

- Private scientific model-claim evaluation from customer-owned prediction CSVs
- Molecular property, ADMET-style, assay activity, and generic regression/classification workflows
- External prediction evaluation for customer-owned or vendor-owned models
- Config-based local runner with YAML workflows
- Local FastAPI service for product-style integrations
- Evidence dashboard API for sanitized run metadata
- Dashboard-safe sync/export commands that avoid raw data upload
- Network-ready evaluation-suite identity metadata for sanitized private leaderboards
- Sanitized private leaderboard API and dashboard views by evaluation metric
- Ed25519-signed dashboard sync with runner public-key verification
- Organization-scoped dashboard API keys, trusted-header SSO proxy support, idempotent sync, rate limits, readiness/metrics, audit retention, and SQLite backup/restore
- PostgreSQL dashboard storage for production deployments
- Verifiable run manifests binding configs, reports, audit logs, and artifact hashes
- Privacy-preserving runner attestation metadata in verification manifests
- Dockerized local runner for customer pilots
- Adapter interface for scientific model integrations
- Dependency-light hashed SMILES fingerprints
- Optional RDKit Morgan fingerprint adapter
- Random forest regression/classification baseline
- Regression metrics: MAE, RMSE, R2
- Classification metrics: accuracy, F1, AUROC
- Error slice analysis for model debugging
- DP-style metric reporting
- Local membership-inference risk scoring for trained molecule baselines and split-labeled prediction exports
- Privacy-risk publishability gates for model-claim release decisions
- Aggregate release guards for cross-lab evaluation evidence
- Dataset and prediction summaries
- Single-client local evaluation
- Multi-client private evaluation over a directory of lab CSVs
- Weighted aggregate evaluation reports
- Model comparison reports across multiple configs
- Markdown and JSON report export
- CLI entrypoint
- CI tests across Python 3.10, 3.11, and 3.12

## Install

```bash
pip install -e .
```

API server support:

```bash
pip install -e '.[api]'
```

Optional RDKit support:

```bash
pip install -e '.[rdkit]'
```

Or install dependencies manually:

```bash
pip install -r requirements.txt
```

## Config-based runner

The recommended customer workflow is to run an evaluation from a YAML config:

```bash
privatelabbench run configs/prediction_eval.yaml
```

Validate a config before running it:

```bash
privatelabbench validate-config configs/prediction_eval.yaml
```

Example config:

```yaml
project: kinase-prediction-demo
workflow: predictions

benchmark:
  id: kinase-private-prediction
  version: "2026.05"
  suite: molecular-property
  domain: molecules

input:
  path: examples/predictions_demo.csv
  target_column: label
  prediction_column: pred
  # Optional. Enables membership-inference risk scoring when present.
  # split_column: split
  task_type: regression

privacy:
  mode: dp
  epsilon: 8
  sensitivity: 1
  seed: 13
  risk_policy:
    max_level: moderate
    max_member_advantage: 0.35
    max_attack_auc: 0.85
  # Federated workflows can also require aggregate release thresholds.
  # aggregate_policy:
  #   min_clients: 3
  #   min_total_samples: 100
  #   min_client_samples: 20

report:
  markdown: reports/kinase_prediction_eval.md
  json: reports/kinase_prediction_eval.json
  manifest: reports/kinase_prediction_manifest.json
```

Supported workflows:

```text
predictions  evaluate customer-owned model outputs
molecules     train/evaluate the built-in molecule baseline
federated     evaluate a directory of private lab CSVs and aggregate reports
```

Included configs:

```text
configs/prediction_eval.yaml
configs/molecule_eval.yaml
configs/molecule_eval_rdkit.yaml
configs/federated_eval.yaml
```

## Local API server

The API wraps the same local runner so a dashboard, desktop app, or customer backend can launch evaluations without raw data leaving the customer environment.

Start the server:

```bash
export PRIVATELABBENCH_API_KEY=dev-secret
privatelabbench serve --host 127.0.0.1 --port 8000
```

Run an existing config:

```bash
curl -X POST http://127.0.0.1:8000/v1/runs \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: dev-secret' \
  -d '{"config_path":"configs/prediction_eval.yaml","run_id":"demo-run"}'
```

Fetch run metadata or reports:

```bash
curl -H 'x-api-key: dev-secret' http://127.0.0.1:8000/v1/runs/demo-run
curl -H 'x-api-key: dev-secret' http://127.0.0.1:8000/v1/runs/demo-run/report/markdown
```

If `PRIVATELABBENCH_API_KEY` is unset, the local API runs without authentication for development only.

## Verifiable run manifests

Config-driven runs write a run manifest next to the reports. The manifest binds the config, JSON report, Markdown report, audit log, benchmark identity, runner identity, report payload hash, and artifact hashes into one verification bundle.

Verify a manifest:

```bash
privatelabbench verify-manifest reports/kinase_prediction_manifest.json
```

When `PRIVATELABBENCH_SIGNING_SECRET` or `report.signing_secret` is set, the JSON report and manifest are both HMAC-signed.

## Evidence dashboard sync

PrivateLabBench has a hosted evidence-dashboard path that keeps raw lab data local. The local runner evaluates data, writes full local reports, then sends only sanitized metadata such as project name, workflow, sample counts, reported/private metrics, privacy mode, and artifact hashes.

One-command local demo on Windows:

```powershell
.\scripts\demo_dashboard.ps1 -OpenDashboard
```

One-command local demo on macOS/Linux:

```bash
bash scripts/demo_dashboard.sh
```

The demo starts the dashboard API if needed, syncs `configs/prediction_eval.yaml`, and prints the browser URL.

Start the dashboard API:

```bash
export PRIVATELABBENCH_DASHBOARD_API_KEY=dashboard-secret
privatelabbench serve-dashboard --host 127.0.0.1 --port 8010
```

Export a dashboard-safe payload without sending it anywhere:

```bash
privatelabbench export-sanitized configs/prediction_eval.yaml \
  --organization-id acme-lab \
  --out reports/sanitized_payload.json
```

Sync sanitized metrics to the dashboard API:

```bash
privatelabbench sync-dashboard configs/prediction_eval.yaml \
  --endpoint http://127.0.0.1:8010 \
  --api-key dashboard-secret \
  --organization-id acme-lab
```

Signed runner sync:

```bash
export PRIVATELABBENCH_RUNNER_ID=acme-runner-1
export PRIVATELABBENCH_RUNNER_PRIVATE_KEY=/secure/acme-runner-ed25519.pem
export PRIVATELABBENCH_RUNNER_PUBLIC_KEYS_FILE=/secure/dashboard-runner-public-keys.json
```

When the dashboard has `PRIVATELABBENCH_RUNNER_PUBLIC_KEYS` or `PRIVATELABBENCH_RUNNER_PUBLIC_KEYS_FILE` configured, `/v1/runs` accepts only payloads signed by a registered runner key.

Inspect synced runs:

```bash
curl -H 'x-api-key: dashboard-secret' http://127.0.0.1:8010/v1/runs
curl -H 'x-api-key: dashboard-secret' http://127.0.0.1:8010/v1/evidence
curl -H 'x-api-key: dashboard-secret' 'http://127.0.0.1:8010/v1/leaderboards/kinase-private-prediction?metric=rmse'
curl -H 'x-api-key: dashboard-secret' http://127.0.0.1:8010/v1/audit-events
curl http://127.0.0.1:8010/ready
curl http://127.0.0.1:8010/metrics
```

Browser dashboard:

```text
http://127.0.0.1:8010/?api_key=dashboard-secret
```

Click a run ID in the dashboard to inspect sanitized metrics, privacy metadata, artifact hashes, and related audit events.
Open `/evidence` to inspect synced model-claim evidence, recommendations, privacy gates, and verification status.
Open `/leaderboards/{benchmark_id}?metric=rmse` to rank sanitized, publishable runs for an evaluation suite.

Dashboard operators can back up, restore, and prune audit events:

```bash
privatelabbench backup-dashboard --out backups/dashboard.db
privatelabbench restore-dashboard --from-backup backups/dashboard.db --force
privatelabbench prune-dashboard-audit --retention-days 365
```

For production storage, set `PRIVATELABBENCH_DASHBOARD_DATABASE_URL=postgresql://...` and install the `postgres` extra. SQLite remains the default for local pilots.
Use [`docs/postgres_integration_testing.md`](docs/postgres_integration_testing.md) to validate the live PostgreSQL backend with Docker.

The sync layer intentionally excludes raw rows, SMILES strings, local dataset paths, prediction summaries, client-level raw details, and free-form private lab data.

## Adapter-based molecule evaluation

Default hashed adapter:

```yaml
model:
  adapter: hashed_random_forest
  fingerprint: hashed
  n_bits: 256
  n_estimators: 200
```

RDKit adapter:

```yaml
model:
  adapter: rdkit_random_forest
  fingerprint: rdkit_morgan
  n_bits: 2048
  radius: 2
  n_estimators: 200
```

See [`docs/ADAPTERS.md`](docs/ADAPTERS.md) for the adapter roadmap.

## Model comparison

Run multiple configs and produce one benchmark comparison report:

```bash
privatelabbench compare configs/prediction_eval.yaml configs/molecule_eval.yaml \
  --report reports/model_comparison.md \
  --json-report reports/model_comparison.json
```

## Docker local runner

CI publishes the main-branch image to GitHub Container Registry:

```bash
docker pull ghcr.io/dipeshbabu/private-lab-bench:latest
docker pull ghcr.io/dipeshbabu/private-lab-bench:0.10.0
```

Build the local runner image:

```bash
docker build -t privatelabbench:local .
```

On Linux hosts, make sure the mounted report directory is writable by the container user:

```bash
mkdir -p reports
chmod 777 reports
```

Run the included demo:

```bash
docker run --rm \
  -v "$PWD/reports:/app/reports" \
  privatelabbench:local run configs/prediction_eval.yaml
```

Run against customer-owned local data:

```bash
docker run --rm \
  -v "$PWD/customer_data:/data" \
  -v "$PWD/reports:/app/reports" \
  privatelabbench:local run /data/customer_eval.yaml
```

See [`docs/production_deployment.md`](docs/production_deployment.md), [`docs/customer_onboarding.md`](docs/customer_onboarding.md), and [`docs/pilot_checklist.md`](docs/pilot_checklist.md) for the recommended pilot workflow.

Production-style dashboard deployment:

```bash
cp .env.example .env
docker compose -f docker-compose.prod.yml --env-file .env up -d dashboard
```

## Single-client quickstart

```bash
privatelabbench eval-molecules examples/molecules_demo.csv --target label --privacy dp --epsilon 8
```

Expected output:

```text
PrivateLabBench molecule evaluation
Task: regression
Samples: 20
Model: RandomForestRegressor
Clean metrics: ...
Reported metrics: ...
Report saved to: reports/molecule_eval_report.md
```

An example generated report is available at [`examples/reports/molecule_eval_report.md`](examples/reports/molecule_eval_report.md).

## External prediction evaluation

Evaluate predictions from a customer-owned model without integrating model code into PrivateLabBench:

```bash
privatelabbench eval-predictions examples/predictions_demo.csv \
  --target label \
  --prediction-column pred \
  --privacy dp \
  --epsilon 8 \
  --report reports/prediction_eval_report.md \
  --json-report reports/prediction_eval_report.json
```

Expected input format:

```csv
smiles,label,pred
CCO,0.12,0.14
CCN,0.20,0.23
c1ccccc1,0.74,0.71
```

This is the easiest customer workflow: they run their own model locally, add a prediction column, and PrivateLabBench generates privacy-preserving Markdown and JSON evaluation reports.

## Model claim evidence reports

Generate a signed evidence package for a specific model claim:

```bash
privatelabbench evidence configs/customer_prediction_eval.yaml \
  --claim "Vendor model improves RMSE versus our internal baseline on private assay data"
```

For baseline comparison, include a baseline prediction column in the same local CSV and config:

```yaml
claim:
  text: Vendor model improves RMSE versus internal baseline
  decision_metric: rmse
  direction: lower_is_better
  minimum_lift: 0.10

input:
  target_column: label
  prediction_column: vendor_pred
  baseline_prediction_column: baseline_pred
```

The evidence command writes a Markdown report and signed JSON report with the claim, metrics, baseline comparison, privacy gate, manifest verification result, sharing boundary, and a `go`, `no-go`, or `needs-review` recommendation.
It also writes an evidence manifest that binds the evidence Markdown, evidence JSON, and source run manifest into one verification bundle.

Sync sanitized model-claim evidence to the hosted dashboard:

```bash
privatelabbench sync-evidence configs/customer_prediction_eval.yaml \
  --endpoint https://dashboard.example.com \
  --api-key replace-with-customer-secret \
  --organization-id customer-lab
```

The dashboard stores only sanitized decision metadata: claim text, recommendation, decision metric, relative lift, privacy gate status, manifest verification status, and artifact hashes.
Evidence sync is idempotent by organization and evidence payload hash, so retrying a sync does not create duplicate evidence records.

If the CSV includes a split column, PrivateLabBench can also estimate aggregate membership-inference risk from train/member rows versus test/nonmember rows:

```bash
privatelabbench eval-predictions customer_predictions.csv \
  --target label \
  --prediction-column pred \
  --split-column split \
  --report reports/prediction_eval_report.md \
  --json-report reports/prediction_eval_report.json
```

Accepted split values include `train`, `test`, `member`, `nonmember`, `1`, and `0`. Only aggregate privacy-risk metadata is reported.

## Multi-client private evaluation

Simulate several private labs, each with its own local CSV:

```bash
privatelabbench eval-federated examples/labs --target label --privacy dp --epsilon 8
```

Expected output:

```text
PrivateLabBench federated evaluation
Clients: 3
Total samples: 60
Task type(s): regression
Model(s): RandomForestRegressor

lab_a:
  samples: 20
  clean metrics: ...
  reported metrics: ...

Aggregate reported metrics: ...
Report saved to: reports/federated_eval_report.md
```

An example federated report is available at [`examples/reports/federated_eval_report.md`](examples/reports/federated_eval_report.md).

## CSV format

```csv
smiles,label
CCO,0.12
CCN,0.20
c1ccccc1,0.74
```

For classification tasks, labels should be `0` or `1`. For regression tasks, labels can be continuous values.

## Project files

- [`configs/`](configs/): example local runner configs
- [`configs/customer_prediction_eval.template.yaml`](configs/customer_prediction_eval.template.yaml): customer-owned prediction eval template
- [`docs/ADAPTERS.md`](docs/ADAPTERS.md): adapter interface and model integration guide
- [`docs/customer_onboarding.md`](docs/customer_onboarding.md): customer pilot guide
- [`docs/dashboard_deployment.md`](docs/dashboard_deployment.md): hosted dashboard deployment guide
- [`docs/production_deployment.md`](docs/production_deployment.md): production compose and customer pilot runbook
- [`docs/postgres_integration_testing.md`](docs/postgres_integration_testing.md): live PostgreSQL backend test workflow
- [`docs/pilot_quickstart.md`](docs/pilot_quickstart.md): customer self-service pilot quickstart
- [`docs/pilot_checklist.md`](docs/pilot_checklist.md): pilot readiness checklist
- [`docs/roadmap.md`](docs/roadmap.md): staged product and research roadmap
- [`CONTRIBUTING.md`](CONTRIBUTING.md): development and privacy principles
- [`CHANGELOG.md`](CHANGELOG.md): release notes
- [`.github/workflows/ci.yml`](.github/workflows/ci.yml): automated tests and CLI smoke tests

## Roadmap

- Trust-report templates for model vendor diligence, partner data collaborations, and internal go/no-go reviews
- Dashboard filters, run detail pages, and deployment templates
- ChemBERTa, MolFormer, Uni-Mol, and GNN adapters
- Protein, microscopy, robotics, and materials prediction tasks
- Membership-inference and property-inference risk scoring
- Model cards and customer-facing privacy risk histories
- SOC2-ready tenant metadata, audit trails, and deployment templates

## Non-goals for the current MVP

PrivateLabBench is not a clinical or regulated diagnostic product, does not upload raw data, and does not perform federated training yet. It is a private evaluation and trust layer for scientific AI claims, designed to start with local evidence generation before expanding into secure multi-party benchmark networks.
