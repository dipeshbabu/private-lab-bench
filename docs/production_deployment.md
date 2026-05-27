# Production Deployment

This guide is for a customer pilot or production-like demo where the hosted dashboard runs as a service and customers run evaluations locally.

## 1. Prepare Environment

Copy the example environment file and replace every `change-me` value:

```bash
cp .env.example .env
```

Required dashboard values:

```text
PRIVATELABBENCH_ENV=production
PRIVATELABBENCH_DASHBOARD_API_KEY=<unique-customer-secret>
PRIVATELABBENCH_DASHBOARD_DB=/data/dashboard.db
PRIVATELABBENCH_RUNNER_PUBLIC_KEYS_FILE=/data/runner_public_keys.json
```

Optional local API values:

```text
PRIVATELABBENCH_API_KEY=<unique-local-api-secret>
PRIVATELABBENCH_RUN_ROOT=/data/runs
```

Signed sync runner values:

```text
PRIVATELABBENCH_RUNNER_ID=<registered-runner-id>
PRIVATELABBENCH_RUNNER_PRIVATE_KEY=<ed25519-private-key-pem-or-path>
```

When `PRIVATELABBENCH_RUNNER_PUBLIC_KEYS` or `PRIVATELABBENCH_RUNNER_PUBLIC_KEYS_FILE` is configured on the dashboard, every `/v1/runs` sync must include a valid Ed25519 runner signature. The registry is a JSON object mapping runner IDs to public key PEM strings.

Use one unique dashboard API key per customer environment. Do not reuse demo keys.

## 2. Start The Dashboard

```bash
docker compose -f docker-compose.prod.yml --env-file .env up -d dashboard
```

Check health:

```bash
curl http://localhost:8010/health
```

Open the browser UI:

```text
http://localhost:8010/?api_key=<unique-customer-secret>
```

For a real customer deployment, put the dashboard behind HTTPS with a reverse proxy or platform load balancer. Route external traffic to container port `8010`.

## 3. Run A Customer Evaluation

Customers keep their CSVs and full reports in their own environment. Before running:

```bash
privatelabbench validate-config configs/customer_prediction_eval.yaml
```

Run and sync sanitized metadata:

```bash
privatelabbench sync-dashboard configs/customer_prediction_eval.yaml \
  --endpoint https://dashboard.example.com \
  --api-key "$PRIVATELABBENCH_DASHBOARD_API_KEY" \
  --organization-id customer-lab
```

Docker runner option:

```bash
mkdir -p reports
chmod 777 reports

docker run --rm \
  -v "$PWD/customer_data:/data:ro" \
  -v "$PWD/reports:/app/reports" \
  ghcr.io/dipeshbabu/private-lab-bench:0.10.0 \
  validate-config /data/customer_prediction_eval.yaml

docker run --rm \
  -v "$PWD/customer_data:/data:ro" \
  -v "$PWD/reports:/app/reports" \
  ghcr.io/dipeshbabu/private-lab-bench:0.10.0 \
  sync-dashboard /data/customer_prediction_eval.yaml \
    --endpoint https://dashboard.example.com \
    --api-key "$PRIVATELABBENCH_DASHBOARD_API_KEY" \
    --organization-id customer-lab
```

## 4. Optional Local API

Start the API service only when an integration needs to launch private runs through HTTP:

```bash
docker compose -f docker-compose.prod.yml --env-file .env --profile api up -d api
```

Check health:

```bash
curl http://localhost:8000/health
```

Launch a run:

```bash
curl -X POST http://localhost:8000/v1/runs \
  -H "Content-Type: application/json" \
  -H "x-api-key: $PRIVATELABBENCH_API_KEY" \
  -d '{"config_path":"configs/prediction_eval.yaml","run_id":"demo-run"}'
```

## 5. Operational Checks

Before handing the environment to a customer:

- Confirm `docker compose -f docker-compose.prod.yml --env-file .env ps` shows a healthy dashboard.
- Confirm `/health` returns `status: ok`.
- Confirm the dashboard requires the API key.
- Confirm signed sync is enforced when runner public keys are configured.
- Run one demo sync and open the run detail page.
- Confirm synced dashboard payloads do not include raw rows, SMILES strings, dataset paths, prediction summaries, or full reports.
- Confirm the Docker volume `privatelabbench_dashboard-data` is retained across restarts.

## 6. Troubleshooting

`PrivateLabBench production configuration is invalid`

The service started with `PRIVATELABBENCH_ENV=production` but required secrets or storage paths are missing. Check `.env` and restart the service.

Dashboard container is unhealthy

Check logs:

```bash
docker compose -f docker-compose.prod.yml --env-file .env logs dashboard
```

Sync returns `401`

The customer runner API key does not match `PRIVATELABBENCH_DASHBOARD_API_KEY` in the dashboard environment.

Permission denied writing reports

Make the host report directory writable by the container user:

```bash
mkdir -p reports
chmod 777 reports
```
