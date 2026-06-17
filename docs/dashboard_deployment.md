# Evidence Dashboard Deployment

This guide describes the deployed PrivateLabBench shape for pilots: customers run evaluations locally, while a hosted evidence dashboard receives only sanitized evaluation metadata.

## Architecture

```text
Customer private CSV/model outputs
        |
        v
PrivateLabBench local runner
        |
        | sanitized evidence JSON payload only
        v
Evidence dashboard API/UI
```

The dashboard does not receive raw rows, SMILES strings, local dataset paths, prediction summaries, client-level raw details, or free-form private lab data.

## Evidence Dashboard

Production compose deployment:

```bash
cp .env.example .env
docker compose -f docker-compose.prod.yml --env-file .env up -d dashboard
```

See [`production_deployment.md`](production_deployment.md) for the full operator runbook.

Run the dashboard service from the published image:

```bash
docker pull ghcr.io/dipeshbabu/private-lab-bench:0.10.0

docker run -d \
  --name privatelabbench-dashboard \
  -p 8010:8010 \
  -e PRIVATELABBENCH_DASHBOARD_API_KEY="replace-with-customer-secret" \
  -e PRIVATELABBENCH_DASHBOARD_DB="/data/dashboard.db" \
  -v privatelabbench-dashboard-data:/data \
  ghcr.io/dipeshbabu/private-lab-bench:0.10.0 \
  serve-dashboard --host 0.0.0.0 --port 8010
```

For a production pilot, put this service behind HTTPS with a reverse proxy or platform load balancer. Terminate TLS before the container and route traffic to port `8010`.

Health check:

```bash
curl https://dashboard.example.com/health
curl https://dashboard.example.com/ready
```

Metrics endpoint:

```bash
curl https://dashboard.example.com/metrics
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

curl -H "x-api-key: replace-with-customer-secret" \
  https://dashboard.example.com/v1/evidence
```

## Environment Variables

`PRIVATELABBENCH_DASHBOARD_API_KEY`

Shared API key required for sync, API calls, and browser dashboard access. Use a unique value per pilot or customer environment.

`PRIVATELABBENCH_DASHBOARD_API_KEYS`

Optional enterprise mode. JSON object mapping organization IDs to API keys, for example:

```json
{"customer-lab":"replace-with-customer-secret"}
```

When this is set, `/v1/runs` and `/v1/evidence` require the API key assigned to the synced payload's `organization_id`. The global key still works as an operator key when configured.

`PRIVATELABBENCH_DASHBOARD_DB`

SQLite database path for sanitized dashboard metadata. Mount this path to persistent storage in Docker or your deployment platform. This is the default local and pilot storage mode.

`PRIVATELABBENCH_DASHBOARD_DATABASE_URL`

Optional PostgreSQL connection URL for production dashboard storage, for example:

```text
postgresql://privatelabbench:secret@postgres.example.com:5432/privatelabbench
```

When this is set, the dashboard uses PostgreSQL instead of SQLite. Install with the `postgres` extra or use a container image that includes `psycopg`.

`PRIVATELABBENCH_DASHBOARD_RATE_LIMIT_PER_MINUTE`

Optional per-key or per-client request limit. `0` or an empty value disables dashboard rate limiting. Health, readiness, and metrics endpoints are excluded so orchestrator checks remain stable.

`PRIVATELABBENCH_AUDIT_RETENTION_DAYS`

Optional audit-event retention window. When set, dashboard requests prune audit events older than this number of days. Use `privatelabbench prune-dashboard-audit --retention-days <days>` for an explicit maintenance run.

`PRIVATELABBENCH_DASHBOARD_TRUSTED_IDENTITY_HEADER`

Optional SSO proxy integration for dashboard read access. Set this only behind a trusted OIDC/SAML proxy that authenticates the user and injects an identity header, for example `x-auth-request-email`.

`PRIVATELABBENCH_DASHBOARD_ALLOWED_IDENTITY_DOMAINS`

Optional comma-separated allowlist for trusted identity email domains, for example `customer.com,partner.org`.

## Operations

Create a SQLite dashboard database backup:

```bash
privatelabbench backup-dashboard --out /data/backups/dashboard-$(date +%Y%m%d).db
```

Restore a dashboard database from backup:

```bash
privatelabbench restore-dashboard \
  --from-backup /data/backups/dashboard-20260616.db \
  --force
```

Prune old audit events manually:

```bash
privatelabbench prune-dashboard-audit --retention-days 365
```

For PostgreSQL, use `pg_dump`, `pg_restore`, or managed database point-in-time recovery. The `backup-dashboard` and `restore-dashboard` commands are intentionally SQLite-only.

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

Then they sync sanitized evidence metadata to the hosted dashboard:

```bash
privatelabbench sync-dashboard customer_eval.yaml \
  --endpoint https://dashboard.example.com \
  --api-key replace-with-customer-secret \
  --organization-id customer-lab
```

For model-claim evidence, use:

```bash
privatelabbench sync-evidence customer_eval.yaml \
  --endpoint https://dashboard.example.com \
  --api-key replace-with-customer-secret \
  --organization-id customer-lab
```

Docker runner option:

```bash
docker run --rm \
  -v "$PWD/customer_data:/data" \
  -v "$PWD/reports:/app/reports" \
  ghcr.io/dipeshbabu/private-lab-bench:0.10.0 \
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
- model-claim evidence: claim, recommendation, metric lift, privacy gate, verification status, and artifact hashes

Sync is idempotent by organization and source run/evidence identifier. Retried syncs return the existing dashboard record instead of creating duplicates.

## Pilot Checklist

Before a customer pilot:

- Use HTTPS for the hosted dashboard endpoint.
- Generate a unique dashboard API key for the customer.
- Mount `PRIVATELABBENCH_DASHBOARD_DB` to persistent storage or configure `PRIVATELABBENCH_DASHBOARD_DATABASE_URL`.
- Confirm `/health` returns `{"status":"ok"}`.
- Confirm `/ready` returns database counts.
- Scrape or inspect `/metrics`.
- Create and verify a dashboard backup.
- Run one demo sync with sample data.
- Have the customer run one sync from their local config.
- Confirm dashboard output does not contain local dataset paths or raw data.
- Confirm the run detail page gives enough evidence for a go/no-go model decision.
- Confirm `/evidence` shows the synced model-claim recommendation.

## Current Limits

- Authentication is API-key based.
- The dashboard defaults to SQLite for pilot simplicity and supports PostgreSQL for production storage.
- Browser access can use `?api_key=...`; use HTTPS and customer-specific keys.
- Organization-scoped API keys isolate tenant sync payloads.
- Browser/API read access can trust an upstream SSO proxy identity header, but PrivateLabBench does not run its own IdP flow.
- Artifact hashes are synced, not full report files.
- Evidence reports are synced as sanitized decision metadata, not raw report contents.
- Use organization-scoped API keys for multi-customer hosted pilots.
