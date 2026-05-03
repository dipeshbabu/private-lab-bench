# Hosted Dashboard Deployment

This guide describes the deployed PrivateLabBench shape for pilots: customers run evaluations locally, while a hosted dashboard receives only sanitized benchmark metadata.

## Architecture

```text
Customer private CSV/model outputs
        |
        v
PrivateLabBench local runner
        |
        | sanitized JSON payload only
        v
Hosted dashboard API/UI
```

The dashboard does not receive raw rows, SMILES strings, local dataset paths, prediction summaries, client-level raw details, or free-form private lab data.

## Hosted Dashboard

Run the dashboard service from the published image:

```bash
docker pull ghcr.io/dipeshbabu/private-lab-bench:0.9.0

docker run -d \
  --name privatelabbench-dashboard \
  -p 8010:8010 \
  -e PRIVATELABBENCH_DASHBOARD_API_KEY="replace-with-customer-secret" \
  -e PRIVATELABBENCH_DASHBOARD_DB="/data/dashboard.db" \
  -v privatelabbench-dashboard-data:/data \
  ghcr.io/dipeshbabu/private-lab-bench:0.9.0 \
  serve-dashboard --host 0.0.0.0 --port 8010
```

For a production pilot, put this service behind HTTPS with a reverse proxy or platform load balancer. Terminate TLS before the container and route traffic to port `8010`.

Health check:

```bash
curl https://dashboard.example.com/health
```

Browser UI:

```text
https://dashboard.example.com/?api_key=replace-with-customer-secret
```

The run table links each run ID to a detail page with sanitized metrics, privacy metadata, artifact hashes, and related audit events.

API:

```bash
curl -H "x-api-key: replace-with-customer-secret" \
  https://dashboard.example.com/v1/runs
```

## Environment Variables

`PRIVATELABBENCH_DASHBOARD_API_KEY`

Shared API key required for sync, API calls, and browser dashboard access. Use a unique value per pilot or customer environment.

`PRIVATELABBENCH_DASHBOARD_DB`

SQLite database path for sanitized dashboard metadata. Mount this path to persistent storage in Docker or your deployment platform.

## Customer Runner

Customers run the local runner on their own machine or inside their own environment. Their config points to local private files:

```yaml
project: customer-model-eval
workflow: predictions

input:
  path: /customer/private/predictions.csv
  target_column: label
  prediction_column: prediction
  task_type: regression

privacy:
  mode: dp
  epsilon: 8
  sensitivity: 1
  seed: 13

report:
  markdown: reports/customer_eval.md
  json: reports/customer_eval.json

audit:
  path: reports/customer_audit.jsonl
```

Then they sync sanitized metadata to the hosted dashboard:

```bash
privatelabbench sync-dashboard customer_eval.yaml \
  --endpoint https://dashboard.example.com \
  --api-key replace-with-customer-secret \
  --organization-id customer-lab
```

Docker runner option:

```bash
docker run --rm \
  -v "$PWD/customer_data:/data" \
  -v "$PWD/reports:/app/reports" \
  ghcr.io/dipeshbabu/private-lab-bench:0.9.0 \
  sync-dashboard /data/customer_eval.yaml \
    --endpoint https://dashboard.example.com \
    --api-key replace-with-customer-secret \
    --organization-id customer-lab
```

## Data Boundary

Stays local:

- raw CSV rows
- SMILES strings and molecule identifiers
- target and prediction columns
- local dataset paths
- full JSON/Markdown reports
- audit log files
- model code and model outputs

Synced to dashboard:

- organization id
- project name
- workflow name
- task type
- sample/client counts
- reported metrics
- privacy metadata
- artifact names and SHA256 hashes
- sanitized scalar metadata

## Pilot Checklist

Before a customer pilot:

- Use HTTPS for the hosted dashboard endpoint.
- Generate a unique dashboard API key for the customer.
- Mount `PRIVATELABBENCH_DASHBOARD_DB` to persistent storage.
- Confirm `/health` returns `{"status":"ok"}`.
- Run one demo sync with sample data.
- Have the customer run one sync from their local config.
- Confirm dashboard output does not contain local dataset paths or raw data.

## Current Limits

- Authentication is API-key based.
- The dashboard uses SQLite for pilot simplicity.
- Browser access can use `?api_key=...`; use HTTPS and customer-specific keys.
- There is no multi-user login or role model yet.
- Artifact hashes are synced, not full report files.
